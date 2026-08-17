import { useEffect, useState } from "react";
import { AnimatePresence, motion } from "framer-motion";
import { Button, Tooltip } from "@heroui/react";
import { ArrowUpToLine } from "@gravity-ui/icons";

const SCROLL_THRESHOLD = 300;

export function BackToTop() {
  const [visible, setVisible] = useState(false);

  useEffect(() => {
    const onScroll = () => {
      setVisible(window.scrollY > SCROLL_THRESHOLD);
    };
    onScroll();
    window.addEventListener("scroll", onScroll, { passive: true });
    return () => window.removeEventListener("scroll", onScroll);
  }, []);

  const scrollToTop = () => {
    window.scrollTo({ top: 0, behavior: "smooth" });
  };

  return (
    <AnimatePresence>
      {visible && (
        <motion.div
          initial={{ opacity: 0, y: 12 }}
          animate={{ opacity: 1, y: 0 }}
          exit={{ opacity: 0, y: 12 }}
          transition={{ duration: 0.2 }}
          className="fixed bottom-6 right-6 z-40"
        >
          <Tooltip.Root delay={400}>
            <Button
              variant="secondary"
              isIconOnly
              size="lg"
              aria-label="回到顶部"
              onPress={scrollToTop}
              className="shadow-lg"
            >
              <ArrowUpToLine />
            </Button>
            <Tooltip.Content>回到顶部</Tooltip.Content>
          </Tooltip.Root>
        </motion.div>
      )}
    </AnimatePresence>
  );
}