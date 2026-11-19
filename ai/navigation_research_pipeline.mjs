// One bounded train→validation-only research trajectory. Test and deployment remain closed.
import fs from 'node:fs';
import path from 'node:path';
import {fileURLToPath} from 'node:url';
import {createHash} from 'node:crypto';
import {runNavigationLearning} from './navigation_learning_runtime.mjs';
import {runValidationSnapshots} from './navigation_snapshot_evaluation.mjs';
const root=path.dirname(path.dirname(fileURLToPath(import.meta.url)));
const read=p=>JSON.parse(fs.readFileSync(p,'utf8').replace(/^\uFEFF/,''));
const sha=p=>createHash('sha256').update(fs.readFileSync(p)).digest('hex');
export async function runNavigationResearch({protocolPath,runRoot,operation}){
 const p=read(protocolPath),hash=sha(protocolPath);
 if(!['initialize','resume'].includes(operation)||p.execution_scope!=='research_training'||p.training_authorized!==true)throw Error('Explicit frozen research training protocol required');
 const evidence=p.evaluator_preflight_evidence,file=path.resolve(root,evidence?.path??'');
 if(!file.startsWith(root+path.sep)||sha(file)!==evidence.sha256)throw Error('Read-only evaluator preflight evidence required');
 const audit=read(file);if(!audit.review_complete||!audit.delivery_complete||!audit.read_only_evaluator_complete)throw Error('Complete reviewed evaluator required before training');
 runRoot=path.resolve(runRoot);fs.mkdirSync(runRoot,{recursive:true});const statusFile=path.join(runRoot,'pipeline-status.json');
 if(fs.existsSync(statusFile)){const old=read(statusFile);if(old.protocol_sha256!==hash)throw Error('Research protocol changed');if(['retained_baseline','candidate_ready_for_review'].includes(old.phase))return old;}
 const lock=path.join(runRoot,'research-pipeline.lock');fs.writeFileSync(lock,JSON.stringify({pid:process.pid,protocol_sha256:hash,started_at:new Date().toISOString()}),{flag:'wx'});
 const status=data=>{const value={updated_at:new Date().toISOString(),pid:process.pid,protocol_sha256:hash,test_opened:false,physical_motor_transport:false,...data};fs.writeFileSync(statusFile+'.pending',JSON.stringify(value,null,2));fs.renameSync(statusFile+'.pending',statusFile);return value;};
 let phase='training';
 try{
  status({phase:'running_training'});
  await runNavigationLearning({protocolPath,runRoot:path.join(runRoot,'training'),operation});
  phase='validation';status({phase:'running_validation_only'});
  const selection=await runValidationSnapshots({protocolPath,trainingRoot:path.join(runRoot,'training'),outputRoot:path.join(runRoot,'evaluation')});
  const selectionFile=path.join(runRoot,'evaluation','selection.json');
  return status({phase:selection.status,selected:selection.selected,selection_path:selectionFile,selection_sha256:sha(selectionFile),review_pending:true,training_and_validation_complete:true});
 }catch(error){status({phase:'needs_repair',failed_phase:phase,error:String(error.message).slice(0,1500)});throw error;}
 finally{fs.unlinkSync(lock);}
}
if(process.argv[1]&&path.resolve(process.argv[1])===fileURLToPath(import.meta.url)){
 const [operation,protocolPath,runRoot,...extra]=process.argv.slice(2);
 if(!operation||!protocolPath||!runRoot||extra.length)throw Error('Use initialize|resume <frozen-research-protocol.json> <dedicated-run-root>');
 console.log(JSON.stringify(await runNavigationResearch({protocolPath,runRoot,operation})));
}
