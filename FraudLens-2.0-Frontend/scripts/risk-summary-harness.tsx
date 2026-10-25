import {createRoot} from 'react-dom/client';
import RiskIndicator, {type RiskPresentation} from '../src/experience/RiskIndicator';
declare global {interface Window {riskFixtures:RiskPresentation[]}}
createRoot(document.getElementById('root')!).render(<main style={{display:'grid',gap:24,padding:12}}>
  <h1>Controlled saved risk summaries — no live inference</h1>
  {window.riskFixtures.map((assessment,index)=><RiskIndicator key={index} assessment={assessment}/>)}
</main>);
