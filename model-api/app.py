import asyncio
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

pipe = None
model_lock = asyncio.Lock()

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

@app.on_event("startup")
async def load_model():
    global pipe
    model_path = "/root/.cache/modelscope/models/hf-diffusers--FLUX.2-dev-bnb-4bit/snapshots/master"
    print("正在加载高阶 FLUX.2 4-bit 融合模型...")
    pipe = Flux2Pipeline.from_pretrained(
        model_path,
        torch_dtype=torch.bfloat16,
        device_map="cuda"
    )
    print("模型常驻显存，服务已 Ready！")
    asyncio.create_task(cleanup_loop())


async def cleanup_loop():
    """后台定时清理过期任务记录，防止字典无限增长。"""
    while True:
        await asyncio.sleep(300)
        cleanup_expired_tasks()

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
    global pipe
    if pipe is None:
        raise HTTPException(status_code=500, detail="模型未加载成功")
    
    async with model_lock:
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
            loop = asyncio.get_event_loop()
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

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)

