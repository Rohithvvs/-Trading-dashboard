import {Info} from 'lucide-react';
export function InfoMetric({title,value,explanation,example}){return <div className="study-metric"><div><span>{title}</span><details name="metric-help"><summary aria-label={`Explain ${title}`}><Info size={14}/></summary><p>{explanation}<br/><b>Example: </b>{example}</p></details></div><strong>{value}</strong></div>;}
