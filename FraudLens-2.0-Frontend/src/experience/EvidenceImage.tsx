import { useEffect, useRef, useState } from 'react';
import { apiImageUrl, Icon } from './shared';
import './evidence-image.css';

// Evidence loads independently: a slow photo must not hold up the case list.
export default function EvidenceImage({ imageId, label, className }: {
  imageId?: string; label: string; className?: string;
}) {
  const element = useRef<HTMLSpanElement>(null);
  const [loaded, setLoaded] = useState({ id: '', src: '' });
  const src = loaded.id === imageId ? loaded.src : '';
  useEffect(() => {
    if (!imageId) return;
    let cancelled = false;
    const load = async () => {
      const url = await apiImageUrl(imageId);
      if (!cancelled) setLoaded({ id: imageId, src: url });
    };
    const observer = new IntersectionObserver(entries => {
      if (entries.some(entry => entry.isIntersecting)) {
        observer.disconnect();
        void load();
      }
    }, { rootMargin: '200px' });
    if (element.current) observer.observe(element.current);
    return () => { cancelled = true; observer.disconnect(); };
  }, [imageId]);
  return <span ref={element} className={['evidence-image', className].filter(Boolean).join(' ')}>
    {src ? <img className={className} src={src} alt={label} />
      : <span role="img" aria-label={label}><Icon name="car" /></span>}
  </span>;
}
