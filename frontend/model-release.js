import{loadAiRegistry}from'./ai-registry.js';
const classes=['plastic_bottle','bottle_cap'],labels=['ขวดพลาสติก','ฝาขวด'];
const $=selector=>document.querySelector(selector);
const validMetrics=value=>value&&['precision','recall','map50','map50_95'].every(key=>Number.isFinite(value[key])&&value[key]>=0&&value[key]<=1);
function asset(value){if(typeof value!=='string'||!/^\/assets\/models\/[a-zA-Z0-9._-]+$/.test(value))throw Error('Invalid model download path');return value;}
export async function initPublishedModel(){
 const registry=await loadAiRegistry().catch(()=>null);let release=registry?.current_release?.release,report=registry?.current_release?.evaluation;
 if(!release){const response=await fetch('/assets/models/release.json',{cache:'no-store'});if(response.status===404)return null;if(!response.ok)throw Error('โหลดข้อมูลโมเดลไม่ได้');release=await response.json();}
 if(release.schema!=='warirak.model-release.v1')throw Error('รูปแบบข้อมูลโมเดลไม่ถูกต้อง');if(!report){const evaluationResponse=await fetch(asset(release.evaluation),{cache:'no-store'});if(!evaluationResponse.ok)throw Error('โหลดผลประเมินไม่ได้');report=await evaluationResponse.json();}
 if(report.schema!=='warirak.evaluation.v1'||report.split!=='test'||report.source!=='measured_evaluation'||!validMetrics(report.overall)||!classes.every(name=>validMetrics(report.classes?.[name])))throw Error('ผลประเมินโมเดลไม่ครบ');
 const data=report.dataset;if(!data?.counts||!Number.isInteger(data.images)||!['train','val','test'].every(key=>Number.isInteger(data.counts[key])))throw Error('จำนวนภาพไม่ถูกต้อง');
 $('#published-model-summary').textContent=`YOLO26n · ภาพ ${report.imgsz} px · ข้อมูลสาธารณะ ${data.images.toLocaleString('th-TH')} ภาพ · ฝึก ${data.counts.train} / validation ${data.counts.val} / test ${data.counts.test}`;
 $('#published-model-score').textContent=`mAP50 ${(report.overall.map50*100).toFixed(1)}% · mAP50–95 ${(report.overall.map50_95*100).toFixed(1)}%`;
 let context=$('#published-model-context');if(!context){context=document.createElement('p');context.id='published-model-context';context.className='model-evaluation-context';$('#published-model-score').after(context);}context.textContent=`รุ่น ${release.version} · ${report.test_is_historical?'ผลจากชุด test เดิมที่เคยเปิดผลแล้ว ไม่ใช่ชุดทดสอบอิสระใหม่ · ':''}${report.validation_previously_exposed?'validation ถูกใช้ประเมินหลายรอบ · ':''}ยังไม่ใช่ผลกล้องบนเรือจริง`;
 const body=$('#published-model-metrics');body.replaceChildren();classes.forEach((name,index)=>{const row=document.createElement('tr');for(const value of[labels[index],...['precision','recall','map50','map50_95'].map(key=>(report.classes[name][key]*100).toFixed(1)+'%')]){const cell=document.createElement('td');cell.textContent=value;row.append(cell);}body.append(row);});
 for(const[key,id]of Object.entries({pytorch:'published-pytorch',ncnn:'published-ncnn',package:'published-package',evaluation:'published-evaluation'})){$('#'+id).href=asset(release[key]);}
 let card=$('#published-model-card');if(!card){card=document.createElement('a');card.id='published-model-card';card.className='button secondary';card.textContent='ข้อมูลโมเดลและข้อจำกัด ↓';card.download='MODEL_CARD_TH.md';$('#published-package').after(card);}card.href=asset(release.model_card||'/assets/models/MODEL_CARD_TH.md');
 $('#published-model-release').hidden=false;$('#model-status-title').textContent='มีโมเดลที่ฝึกจากข้อมูลสาธารณะแล้ว';$('.model-status .state-tag').textContent='PUBLIC-DATA MODEL';$('#model-status-detail').textContent='ดาวน์โหลดโมเดลและผลทดสอบได้ด้านล่าง ยังต้องปรับฝึกและทดสอบกับกล้องบนเรือจริง';
 return{release,report};
}
