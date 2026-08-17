import asyncio
import os
import threading
import time
from fastapi import FastAPI, HTTPException, UploadFile, File, Form
from fastapi.responses import StreamingResponse
from typing import List, Dict
import torch
from PIL import Image
import io
from diffusers import Flux2Pipeline

app = FastAPI(title="FLUX.2 MaaS Enterprise", description="支持角色定义与进度监听的高级多图融合服务")

# ===================== 模型生命周期配置 =====================
# 默认惰性加载：首个请求时才加载模型，空闲超过 IDLE_UNLOAD_SECONDS 后释放显存。
# 生产常驻场景可设 FLUX_EAGER_LOAD=1 启动即预加载（此时不会自动卸载）。
MODEL_PATH = os.getenv(
    "FLUX_MODEL_PATH",
    "/root/.cache/modelscope/models/hf-diffusers--FLUX.2-dev-bnb-4bit/snapshots/master",
)
IDLE_UNLOAD_SECONDS = int(os.getenv("FLUX_IDLE_UNLOAD_SECONDS", "3600"))  # 空闲 1 小时释放显存
UNLOAD_CHECK_INTERVAL = int(os.getenv("FLUX_UNLOAD_CHECK_INTERVAL", "60"))  # 后台巡检间隔
EAGER_LOAD = os.getenv("FLUX_EAGER_LOAD", "0").lower() in ("1", "true", "yes")
# 加载前至少需要的空闲显存（实测该模型加载后占用约 32GB，默认 36GB 预留暂态峰值余量）
MIN_FREE_VRAM_GB = float(os.getenv("FLUX_MIN_FREE_VRAM_GB", "36"))
MIN_FREE_VRAM_BYTES = int(MIN_FREE_VRAM_GB * 1024 ** 3)

# 模型状态机：idle(未加载) -> loading(加载中) -> loaded(可推理)
MODEL_STATE_IDLE = "idle"
MODEL_STATE_LOADING = "loading"
MODEL_STATE_LOADED = "loaded"

pipe = None
model_state = MODEL_STATE_IDLE
load_lock = asyncio.Lock()        # 串行化模型的加载与卸载，防止并发双加载/加载卸载互踩
inference_lock = asyncio.Lock()   # 串行化推理（单卡场景，沿用原有行为）
active_requests = 0               # 正在使用模型的请求数，卸载前必须为 0
model_last_used = 0.0             # 模型最近一次被使用的时间戳（Unix）
load_task = None                  # 后台加载任务（独立于请求，请求取消不影响加载）
load_error = None                 # 最近一次加载失败的错误，供上层转换 503/500

# 全局字典，用于暂存不同请求的实时进度 (实际生产建议用 Redis 或状态机管理)
task_progress: Dict[str, float] = {}
TASK_TTL_SECONDS = 3600  # 任务进度记录过期时间，防止字典无限增长
last_update: Dict[str, float] = {}  # 记录每个任务最后一次更新时间（Unix 时间戳）
cancel_events: Dict[str, threading.Event] = {}  # 每个进行中任务的取消标志，供取消接口触发


def cleanup_expired_tasks():
    """清理超过 TTL 未更新的过期任务记录，防止字典无限增长。"""
    now = time.time()
    expired = [
        task_id
        for task_id, ts in last_update.items()
        if now - ts > TASK_TTL_SECONDS
    ]
    for task_id in expired:
        task_progress.pop(task_id, None)
        last_update.pop(task_id, None)
        cancel_events.pop(task_id, None)


def touch_task(task_id: str, progress: float):
    task_progress[task_id] = progress
    last_update[task_id] = time.time()


def touch_model_usage():
    """刷新模型最后使用时间，供空闲卸载巡检使用。"""
    global model_last_used
    model_last_used = time.time()


def _load_pipe():
    """同步加载模型（阻塞操作），放到线程池执行以免卡住事件循环。"""
    print("正在加载高阶 FLUX.2 4-bit 融合模型...")
    return Flux2Pipeline.from_pretrained(
        MODEL_PATH,
        torch_dtype=torch.bfloat16,
        device_map="cuda"
    )


class InsufficientVramError(Exception):
    """显存不足以加载模型（可恢复，调用方应返回 503）。"""


def check_vram_before_load():
    """加载前预检空闲显存，不足时抛 InsufficientVramError。"""
    if not torch.cuda.is_available():
        return
    torch.cuda.empty_cache()  # 尽量释放缓存，最大化可用空间
    props = torch.cuda.get_device_properties(torch.cuda.current_device())
    free_bytes = props.total_memory - torch.cuda.memory_allocated()
    if free_bytes < MIN_FREE_VRAM_BYTES:
        raise InsufficientVramError(
            f"显存不足：加载模型至少需要 {MIN_FREE_VRAM_GB:.0f}GB 空闲，当前仅 {free_bytes / 1024 ** 3:.1f}GB"
        )


async def _do_load():
    """后台加载模型。所有异常内部消化并存入 load_error，不在任务内 re-raise，
    避免请求取消导致孤儿任务；模型状态与 pipe 由本任务统一维护。"""
    global pipe, model_state, load_error
    load_error = None
    model_state = MODEL_STATE_LOADING
    try:
        check_vram_before_load()
        loop = asyncio.get_running_loop()
        pipe = await loop.run_in_executor(None, _load_pipe)
        model_state = MODEL_STATE_LOADED
        touch_model_usage()
        print("模型加载完成，服务已 Ready")
    except RuntimeError as e:
        if "out of memory" in str(e).lower():
            # OOM 兜底：清理残留分配后转抛可恢复错误，便于上层返回 503
            pipe = None
            model_state = MODEL_STATE_IDLE
            if torch.cuda.is_available():
                torch.cuda.synchronize()
                torch.cuda.empty_cache()
            load_error = InsufficientVramError(f"模型加载失败：显存不足（{str(e)}）")
            print(f"模型加载失败（OOM）: {e}")
            return
        model_state = MODEL_STATE_IDLE
        load_error = e
        print(f"模型加载失败: {e}")
    except Exception as e:
        model_state = MODEL_STATE_IDLE
        load_error = e
        print(f"模型加载失败: {e}")


async def ensure_model() -> bool:
    """惰性加载模型。返回 True 表示模型可用；返回 False 表示正在加载中（调用方应返回 503）。"""
    global load_task
    if pipe is not None:
        return True
    if load_task is not None and not load_task.done():
        return False  # 正在加载，不阻塞排队，让调用方快速失败（503 + Retry-After）
    async with load_lock:
        if pipe is not None:
            return True
        if load_task is not None and not load_task.done():
            return False
        load_task = asyncio.create_task(_do_load())
    # 等待加载完成；请求被取消只取消本次等待，后台任务继续把 pipe/model_state 置好
    await load_task
    if load_error is not None:
        err = load_error
        load_error = None
        raise err
    return pipe is not None


@app.on_event("startup")
async def startup():
    asyncio.create_task(cleanup_loop())
    asyncio.create_task(model_idle_loop())
    if EAGER_LOAD:
        try:
            await ensure_model()
            print("常驻模式（FLUX_EAGER_LOAD=1）：模型已预加载，不会自动卸载")
        except Exception as e:
            print(f"预加载失败（后续请求将自动重试）: {e}")
    else:
        print("惰性加载模式：模型将在首个请求时加载，空闲 1 小时自动释放显存")


async def cleanup_loop():
    """后台定时清理过期任务记录，防止字典无限增长。"""
    while True:
        await asyncio.sleep(300)
        cleanup_expired_tasks()


async def model_idle_loop():
    """后台巡检：模型空闲超过阈值且无请求占用时，释放模型权重与显存。"""
    global pipe, model_state
    while True:
        await asyncio.sleep(UNLOAD_CHECK_INTERVAL)
        if EAGER_LOAD:
            continue  # 常驻模式下永不卸载
        if pipe is None or active_requests > 0:
            continue
        if time.time() - model_last_used <= IDLE_UNLOAD_SECONDS:
            continue
        async with load_lock:
            # 二次复查：等待锁期间可能有新请求进来或模型被重新加载
            if pipe is None or active_requests > 0:
                continue
            if time.time() - model_last_used <= IDLE_UNLOAD_SECONDS:
                continue
            print("模型空闲超时，释放模型权重与显存...")
            pipe = None
            model_state = MODEL_STATE_IDLE
            if torch.cuda.is_available():
                torch.cuda.synchronize()
                torch.cuda.empty_cache()
            print("已释放，下次请求将重新加载")


# 接口 0：健康检查（配合 readiness probe，暴露模型加载状态与显存占用）
@app.get("/v1/health")
async def health():
    cuda_ok = torch.cuda.is_available()
    return {
        "status": "ready" if pipe is not None else model_state,
        "model_loaded": pipe is not None,
        "model_state": model_state,
        "active_requests": active_requests,
        "eager_load": EAGER_LOAD,
        "idle_unload_seconds": IDLE_UNLOAD_SECONDS,
        "cuda_memory_allocated_bytes": torch.cuda.memory_allocated() if cuda_ok else 0,
        "cuda_memory_reserved_bytes": torch.cuda.memory_reserved() if cuda_ok else 0,
    }

# 接口 1：查看生成进度的状态接口
@app.get("/v1/progress/{task_id}")
async def get_progress(task_id: str):
    cleanup_expired_tasks()
    progress = task_progress.get(task_id, 0.0)
    return {"task_id": task_id, "progress": f"{progress:.2%}"}

# 接口 1.5：主动取消某个进行中的生成任务
@app.post("/v1/cancel/{task_id}")
async def cancel_generation(task_id: str):
    event = cancel_events.get(task_id)
    if event is None:
        raise HTTPException(status_code=404, detail=f"任务 {task_id} 不存在或已结束")
    event.set()
    return {"task_id": task_id, "status": "cancelling"}

# 接口 2：高精度图像融合接口（不传图时自动退化为纯文生图）
@app.post("/v1/mix-generation-pro")
async def mix_generation_pro(
    task_id: str = Form(..., description="唯一的任务ID，用于前端查询进度"),
    prompt: str = Form(..., description="控制提示词"),
    num_inference_steps: int = Form(20, description="推理步数"),
    guidance_scale: float = Form(None, description="引导强度，不传则使用模型默认值"),
    background_image: UploadFile = File(None, description="【可选主背景图】不传则进行纯文生图"),
    object_images: List[UploadFile] = File(None, description="【道具/物体图片列表】（可选）"),
    width: int = Form(None, description="【可选输出宽度】不传则由模型决定（文生图默认 1024）"),
    height: int = Form(None, description="【可选输出高度】不传则由模型决定（文生图默认 1024）")
):
    global active_requests
    if num_inference_steps <= 0:
        raise HTTPException(status_code=400, detail="num_inference_steps 必须大于 0")
    active_requests += 1
    try:
        try:
            model_ready = await ensure_model()
        except InsufficientVramError as e:
            # 显存不足：可恢复错误，延长重试窗口避免打爆冷加载
            raise HTTPException(status_code=503, detail=str(e), headers={"Retry-After": "60"})
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"模型加载失败: {str(e)}")
        if not model_ready:
            # 模型仍在加载，不排队阻塞，让客户端退避重试
            raise HTTPException(
                status_code=503,
                detail="模型正在加载，请稍后重试",
                headers={"Retry-After": "10"},
            )

        async with inference_lock:
            touch_model_usage()
            cancel_event = threading.Event()
            cancel_events[task_id] = cancel_event
            try:
                task_progress[task_id] = 0.0  # 初始化进度
                last_update[task_id] = time.time()

                # 1. 严格按角色解析图片（不传任何图片 = 纯文生图）
                images = []

                if background_image is not None:
                    bg_bytes = await background_image.read()
                    if bg_bytes:
                        images.append(Image.open(io.BytesIO(bg_bytes)).convert("RGB"))

                # 后面追加物体图
                if object_images:
                    for file in object_images:
                        obj_bytes = await file.read()
                        if obj_bytes:
                            images.append(Image.open(io.BytesIO(obj_bytes)).convert("RGB"))

                # 2. 定义 Diffusers 步进回调函数，监控模型推理进度
                def step_callback(pipe, step: int, timestep: int, callback_kwargs: dict):
                    # 客户端断开或主动取消时，终止生成
                    if cancel_event.is_set():
                        raise RuntimeError("generation cancelled by client")
                    # 计算当前进度百分比
                    current_progress = (step + 1) / num_inference_steps
                    touch_task(task_id, min(current_progress, 1.0))
                    return callback_kwargs

                # 3. 异步执行 GPU 推理
                loop = asyncio.get_running_loop()
                def run_inference():
                    # 使用 callback_on_step_end 捕获每一步的执行情况
                    kwargs = {
                        "prompt": prompt,
                        "num_inference_steps": num_inference_steps,
                        "callback_on_step_end": step_callback,
                        "callback_on_step_end_tensor_inputs": ["latents"]  # 必须指定一个tensor输入，回调才会生效
                    }
                    if images:
                        # 有图 = 图生图/多图融合；无图 = 纯文生图
                        kwargs["image"] = images
                    if width is not None:
                        # 就近取 16 的倍数，避免 VAE 编码尺寸不合法
                        kwargs["width"] = width // 16 * 16
                    if height is not None:
                        kwargs["height"] = height // 16 * 16
                    if guidance_scale is not None:
                        kwargs["guidance_scale"] = guidance_scale
                    return pipe(**kwargs).images

                result_images = await loop.run_in_executor(None, run_inference)

                # 4. 返回结果
                img_byte_arr = io.BytesIO()
                result_images[0].save(img_byte_arr, format='PNG')
                img_byte_arr.seek(0)

                return StreamingResponse(img_byte_arr, media_type="image/png")

            except RuntimeError as e:
                if cancel_event.is_set() and str(e) == "generation cancelled by client":
                    # 主动取消：正常中止，不算服务端错误
                    return {"task_id": task_id, "status": "cancelled"}
                raise HTTPException(status_code=500, detail=f"融合推理失败: {str(e)}")
            except Exception as e:
                raise HTTPException(status_code=500, detail=f"融合推理失败: {str(e)}")
            finally:
                # 置位取消标志：worker 线程在下一个 step 回调处抛异常，终止推理
                cancel_event.set()
                cancel_events.pop(task_id, None)
                # 无论成功、失败还是请求被取消（CancelledError），都清理任务状态
                task_progress.pop(task_id, None)
                last_update.pop(task_id, None)
                # 推理结束后释放缓存显存（不释放模型权重）
                if pipe is not None and torch.cuda.is_available():
                    torch.cuda.empty_cache()
    finally:
        active_requests -= 1
        touch_model_usage()

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)