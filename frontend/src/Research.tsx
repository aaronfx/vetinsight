import { useState } from 'react'
import report from './research-report.json'

type Example = typeof report.examples[number]

function RecordedImage({ example, threshold, showSource }: { example: Example; threshold: number; showSource: boolean }) {
  const [status, setStatus] = useState<'loading' | 'ready' | 'error'>('loading')
  const visible = example.predictions.filter(prediction => prediction.score >= threshold)
  return <>
    <div className="research-image">
      <img src={example.url} alt={`MIDOG++ canine histology demonstration, source case ${example.case_id}`} onLoad={() => setStatus('ready')} onError={() => setStatus('error')} />
      {status === 'ready' && <svg viewBox={`0 0 ${example.width} ${example.height}`} role="img" aria-label={`${showSource ? example.source_boxes.length : 0} source boxes and ${visible.length} recorded model candidates`}>
        {showSource && example.source_boxes.map(([x, y, width, height], index) => <rect key={`source-${index}`} x={x} y={y} width={width} height={height} className="research-source" />)}
        {visible.map(({ box: [x, y, width, height], score }, index) => <g key={index}><rect x={x} y={y} width={width} height={height} className="research-prediction" /><text x={x} y={Math.max(12, y - 4)} className="research-score">{score.toFixed(3)}</text></g>)}
      </svg>}
    </div>
    {status === 'loading' && <p role="status">Loading demonstration image…</p>}
    {status === 'error' && <p className="error" role="alert">The demonstration image could not be loaded. Refresh the page to retry.</p>}
    <p aria-live="polite">{visible.length} recorded candidates at score ≥ {threshold.toFixed(2)}. Source annotations identify {example.source_boxes.length} mitoses in this tile.</p>
  </>
}

export default function Research() {
  const [selected, setSelected] = useState(0)
  const [threshold, setThreshold] = useState(0.5)
  const [showSource, setShowSource] = useState(true)
  const example = report.examples[selected]
  return <div className="research-workspace">
    <section className="research-status" aria-labelledby="research-status-heading"><span className="badge">Experimental · Recorded run</span>
      <h2 id="research-status-heading">Canine histology mitosis detection</h2>
      <p>A paired experiment on 11 MIDOG++ source cases, completed on {new Date(report.completed_at).toLocaleDateString('en-GB', { timeZone: 'UTC', day: 'numeric', month: 'long', year: 'numeric' })}.</p>
      <p><strong>At score 0.5, both models missed all 138 test mitoses.</strong> Ranked detection and box localization improved, while detection quality remains limited. Patient independence is unverified.</p>
    </section>
    <section aria-labelledby="research-results-heading"><h2 id="research-results-heading">Measured held-out results</h2>
      <div className="research-table-scroll"><table className="research-table"><caption>AP is measured on a 0–1 scale across the full held-out set.</caption><thead><tr><th scope="col">Configuration</th><th scope="col">Selected epoch</th><th scope="col">AP50</th><th scope="col">AP50–95</th><th scope="col">Median box width</th></tr></thead><tbody>
        {report.models.map(model => <tr key={model.name}><th scope="row">{model.name}</th><td>{model.epoch}</td><td>{model.ap50.toFixed(6)}</td><td>{model.ap50_95.toFixed(6)}</td><td>{model.median_width.toFixed(1)} px</td></tr>)}
      </tbody></table></div><p className="muted">Source boxes have a median width of 50 px. AP50 uses IoU 0.5; AP50–95 averages IoU 0.50 through 0.95.</p>
      <div className="research-cohort">{Object.entries(report.cohort).map(([split, counts]) => <div key={split}><h3>{split}</h3><strong>{counts.cases} source cases</strong><p>{counts.tiles.toLocaleString()} tiles · {counts.mitoses} mitosis labels</p></div>)}</div>
    </section>
    <section aria-labelledby="recorded-examples-heading"><h2 id="recorded-examples-heading">Inspect recorded predictions</h2>
      <p><strong>Demonstration data from the public MIDOG++ dataset.</strong> These four selected examples include overlapping candidates and missed targets. They display saved outputs from the revised detector on held-out histology images.</p>
      <div className="research-controls"><label>Demonstration tile<select value={selected} onChange={event => setSelected(Number(event.target.value))}>{report.examples.map((item, index) => <option key={item.id} value={index}>Example {index + 1} · source case {item.case_id}</option>)}</select></label>
        <label>Candidate score threshold · {threshold.toFixed(2)}<input type="range" min="0" max="0.5" step="0.01" value={threshold} onChange={event => setThreshold(Number(event.target.value))} /></label>
        <label className="research-toggle"><input type="checkbox" checked={showSource} onChange={event => setShowSource(event.target.checked)} /> Show source annotations</label></div>
      <p className="research-legend"><span>Green outlines · source labels</span><span>Purple outlines · recorded model candidates</span></p>
      <RecordedImage key={example.id} example={example} threshold={threshold} showSource={showSource} />
      <p className="muted">The slider filters these saved example predictions. Published metrics use the full test set. Model scores require calibration on development data.</p>
    </section>
    <section><h2>Experiment protocol and provenance</h2>
      <p>Faster R-CNN MobileNetV3 Large FPN used COCO initialization and a frozen backbone. Both configurations trained for three epochs with seed 42, batch size two and 32 candidate boxes per tile. Validation AP selected the checkpoint before final test evaluation.</p>
      <p>The revised configuration uses 512-pixel inputs and anchor sizes of 16, 24, 32, 48 and 64 pixels. The baseline uses 256-pixel inputs. Resolution, anchor scales and learning rate change together, so the comparison measures their combined effect.</p>
      <p>Cases were grouped by source ROI identifiers. The dataset contains canine lymphosarcoma histology. Each selected image record and the annotation record specifies CC0. These results apply to this small histology cohort; cytology and diagnostic validation require separate evidence.</p>
      <div className="inline-actions"><a href="/assets/research/experiment-summary.json" download="vetinsight-experiment-summary.json">Download experiment summary</a><a href={report.source_url} target="_blank" rel="noreferrer">MIDOG++ dataset</a><a href={report.paper_url} target="_blank" rel="noreferrer">Dataset publication</a></div>
      <details><summary>Selected checkpoint hashes</summary>{report.models.map(model => <p key={model.name}><strong>{model.name}</strong><code className="research-hash">{model.checkpoint_sha256}</code></p>)}</details>
    </section>
  </div>
}
