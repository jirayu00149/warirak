// Only metadata and measured reports are stored here. Image datasets stay outside D1.
export async function aiRegistry(db,ownerId){
 const [datasets,runs,current]=await Promise.all([
  db.prepare('SELECT id,name,status,image_count,train_count,val_count,test_count,manifest_sha256,updated_at_ms FROM ai_datasets WHERE owner_id=? ORDER BY updated_at_ms DESC LIMIT 20').bind(ownerId).all(),
  db.prepare('SELECT id,dataset_id,status,epoch,total_epochs,validation_json,details_json,started_at_ms,updated_at_ms,finished_at_ms FROM ai_training_runs WHERE owner_id=? ORDER BY updated_at_ms DESC LIMIT 20').bind(ownerId).all(),
  db.prepare('SELECT id,weights_sha256,input_size,release_json,evaluation_json,published_at_ms FROM ai_model_releases WHERE owner_id=? AND active=1 LIMIT 1').bind(ownerId).first()
 ]);
 return{schema:'warirak.ai-registry.v1',storage:'Cloudflare D1',server_time:new Date().toISOString(),datasets:datasets.results,runs:runs.results.map(({validation_json,details_json,...row})=>({...row,validation:JSON.parse(validation_json),details:JSON.parse(details_json)})),current_release:current?{id:current.id,weights_sha256:current.weights_sha256,input_size:current.input_size,published_at_ms:current.published_at_ms,release:JSON.parse(current.release_json),evaluation:JSON.parse(current.evaluation_json)}:null};
}
