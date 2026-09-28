import { useEffect, useRef, useState } from "react";

export default function IntroVideo() {
  const videoRef = useRef<HTMLVideoElement>(null);
  const manuallyControlled = useRef(false);
  const [playing, setPlaying] = useState(false);
  const [muted, setMuted] = useState(true);
  useEffect(() => {
    const video = videoRef.current;
    if (!video) return;
    let visible = false;
    let started = false;
    const reduced = matchMedia("(prefers-reduced-motion: reduce)");
    let pending = false;
    let disposed = false;
    const attempt = () => {
      if (
        !visible ||
        started ||
        pending ||
        disposed ||
        manuallyControlled.current ||
        document.hidden ||
        reduced.matches
      )
        return;
      pending = true;
      void video
        .play()
        .then(() => {
          started = true;
        })
        .catch(() => {
          // Keep the viewport and gesture listeners alive after autoplay denial.
          if (!disposed) setPlaying(false);
        })
        .finally(() => {
          pending = false;
        });
    };
    const observer = new IntersectionObserver(
      (entries) => {
        visible = entries.some((entry) => entry.isIntersecting && entry.intersectionRatio >= 0.45);
        if (visible) attempt();
        else if (!video.paused) {
          video.pause();
          if (!manuallyControlled.current) started = false;
        }
      },
      { threshold: [0, 0.45] },
    );
    const gesture = (event: Event) => {
      if (event.target instanceof Element && event.target.closest(".intro-controls")) return;
      attempt();
    };
    const scroll = () => {
      attempt();
    };
    const lifecycle = () => {
      if (document.hidden || reduced.matches) {
        video.pause();
        if (!manuallyControlled.current) started = false;
      } else attempt();
    };
    reduced.addEventListener("change", lifecycle);
    observer.observe(video);
    video.addEventListener("canplay", attempt);
    document.addEventListener("pointerup", gesture, { passive: true });
    document.addEventListener("touchend", gesture, { passive: true });
    document.addEventListener("keydown", gesture);
    document.addEventListener("visibilitychange", lifecycle);
    window.addEventListener("scroll", scroll, { passive: true });
    return () => {
      disposed = true;
      observer.disconnect();
      video.removeEventListener("canplay", attempt);
      document.removeEventListener("pointerup", gesture);
      document.removeEventListener("touchend", gesture);
      document.removeEventListener("keydown", gesture);
      document.removeEventListener("visibilitychange", lifecycle);
      reduced.removeEventListener("change", lifecycle);
      window.removeEventListener("scroll", scroll);
    };
  }, []);
  const togglePlay = () => {
    manuallyControlled.current = true;
    const video = videoRef.current;
    if (!video) return;
    if (video.paused) void video.play().catch(() => setPlaying(false));
    else video.pause();
  };
  const toggleSound = () => {
    const video = videoRef.current;
    if (!video) return;
    video.muted = !video.muted;
    setMuted(video.muted);
  };
  return (
    <div className="hero-video intro-player">
      <video
        ref={videoRef}
        autoPlay
        muted={muted}
        playsInline
        preload="metadata"
        poster="/intro-poster.jpg"
        aria-label="FraudLens 2.0 introduction"
        onPlay={() => setPlaying(true)}
        onPause={() => setPlaying(false)}
        onEnded={() => setPlaying(false)}
        onVolumeChange={() => setMuted(videoRef.current?.muted ?? true)}
      >
        <source src="/media/intro.mp4" type="video/mp4" />
        Your browser does not support embedded video.
      </video>
      <div className="intro-controls">
        <button
          type="button"
          onClick={togglePlay}
          aria-label={playing ? "Pause video" : "Play video"}
          title={playing ? "Pause" : "Play"}
        >
          <svg viewBox="0 0 24 24" aria-hidden="true">
            {playing ? (
              <>
                <path d="M8 5v14M16 5v14" />
              </>
            ) : (
              <path d="m8 5 11 7-11 7Z" />
            )}
          </svg>
        </button>
        <button
          type="button"
          onClick={toggleSound}
          aria-label={muted ? "Turn sound on" : "Turn sound off"}
          title={muted ? "Sound on" : "Sound off"}
        >
          <svg viewBox="0 0 24 24" aria-hidden="true">
            <path d="M11 5 6 9H3v6h3l5 4Z" />
            {muted ? (
              <path d="m16 9 6 6m0-6-6 6" />
            ) : (
              <>
                <path d="M15 8a6 6 0 0 1 0 8M18 4a11 11 0 0 1 0 16" />
              </>
            )}
          </svg>
        </button>
      </div>
    </div>
  );
}
