import{createTrainer,evaluatePolicy}from'./autonomy.js';
let job=null;
self.onmessage=event=>{try{if(event.data.type==='train'){if(job)throw Error('Training already running');job=createTrainer(event.data.config);run();}}catch(e){self.postMessage({type:'error',message:e.message});job=null;}};
function run(){try{const progress=job.batch(25);self.postMessage({type:'progress',...progress});if(job.completed<job.total)setTimeout(run,0);else{const policy=job.finish();policy.evaluation=evaluatePolicy(policy);self.postMessage({type:'complete',policy});job=null;}}catch(e){self.postMessage({type:'error',message:e.message});job=null;}}
