// A deliberately small simulator. Its observations are synthetic, not real camera detections.
export const ENV_VERSION='warirak-pool-v1';
export const ACTIONS=[{name:'เดินหน้า',left:.65,right:.65},{name:'เลี้ยวซ้าย',left:.25,right:.65},{name:'เลี้ยวขวา',left:.65,right:.25},{name:'หมุนซ้าย',left:-.3,right:.3},{name:'หมุนขวา',left:.3,right:-.3}];
export const STATES=17*3*8;
export function rng(seed){let a=seed>>>0;return()=>{a+=0x6D2B79F5;let t=a;t=Math.imul(t^t>>>15,t|1);t^=t+Math.imul(t^t>>>7,t|61);return((t^t>>>14)>>>0)/4294967296;};}
const clamp=(x,a,b)=>Math.min(b,Math.max(a,x));
const wrap=x=>Math.atan2(Math.sin(x),Math.cos(x));
export class PoolEnv{
 constructor(seed=1){this.reset(seed);}
 reset(seed=1){this.seed=seed;this.random=rng(seed);const r=this.random;this.width=10;this.height=6;this.radius=.19;this.steps=0;this.maxSteps=320;this.done=false;this.terminated=false;this.truncated=false;this.collected=0;this.collisions=0;this.totalReward=0;
  this.obstacles=[];for(let i=0;i<3;i++)this.obstacles.push({x:2+r()*6,y:1+r()*4,r:.25+r()*.3});
  const spawn=()=>{for(let i=0;i<500;i++){const p={x:.7+r()*8.6,y:.7+r()*4.6};if(this.obstacles.every(o=>Math.hypot(p.x-o.x,p.y-o.y)>o.r+.8))return p;}return{x:.7,y:.7};};
  Object.assign(this,spawn());this.heading=r()*Math.PI*2;do{this.target=spawn();}while(Math.hypot(this.target.x-this.x,this.target.y-this.y)<2.2);
  this.target.class_id=r()<.65?0:1;this.drift={x:(r()-.5)*.045,y:(r()-.5)*.045};this.leftGain=.92+r()*.16;this.rightGain=.92+r()*.16;this.route=[[this.x,this.y]];this.trace=[];this.lastAction=null;this.observation=this.observe();return this.observation;
 }
 ray(angle){const dx=Math.cos(angle),dy=Math.sin(angle),rad=this.radius;let best=1.5;
  for(const[t,valid]of[[(rad-this.x)/dx,dx<0],[(this.width-rad-this.x)/dx,dx>0],[(rad-this.y)/dy,dy<0],[(this.height-rad-this.y)/dy,dy>0]])if(valid&&t>=0)best=Math.min(best,t);
  for(const o of this.obstacles){const ox=this.x-o.x,oy=this.y-o.y,b=ox*dx+oy*dy,c=ox*ox+oy*oy-(o.r+rad)**2,d=b*b-c;if(d>=0){const t=-b-Math.sqrt(d);if(t>=0)best=Math.min(best,t);}}
  return Math.max(0,best);
 }
 observe(){const distance=Math.hypot(this.target.x-this.x,this.target.y-this.y),bearing=wrap(Math.atan2(this.target.y-this.y,this.target.x-this.x)-this.heading);
  const visible=Math.abs(bearing)<Math.PI*.48&&distance<4.8;
  const noisyBearing=wrap(bearing+(this.random()-.5)*.04);const bin=visible?clamp(Math.floor((noisyBearing+Math.PI)/(Math.PI*2)*16),0,15):16;
  const range=visible?(distance<.8?0:distance<2?1:2):2;
  const clearance=[this.ray(this.heading+.65),this.ray(this.heading),this.ray(this.heading-.65)];let mask=0;clearance.forEach((v,i)=>{if(v<.65)mask|=1<<i;});
  return{state:(bin*3+range)*8+mask,bearing_bin:bin,distance_bin:range,target_visible:visible,clearance,obstacle_mask:mask};
 }
 step(action){if(this.done)return{observation:this.observation,reward:0,terminated:this.terminated,truncated:this.truncated};
  if(!Number.isInteger(action)||!ACTIONS[action])throw Error('Unknown action');const before=Math.hypot(this.target.x-this.x,this.target.y-this.y),a=ACTIONS[action],dt=.3;
  const left=a.left*this.leftGain,right=a.right*this.rightGain,velocity=(left+right)/2;
  this.heading=wrap(this.heading+(right-left)/.4*dt);this.x+=(Math.cos(this.heading)*velocity+this.drift.x)*dt;this.y+=(Math.sin(this.heading)*velocity+this.drift.y)*dt;this.steps++;this.lastAction=action;
  const distance=Math.hypot(this.target.x-this.x,this.target.y-this.y),bearing=Math.abs(wrap(Math.atan2(this.target.y-this.y,this.target.x-this.x)-this.heading));
  let reward=(before-distance)*3-.045-(action>=3?.02:0);
  const collision=this.x<this.radius||this.x>this.width-this.radius||this.y<this.radius||this.y>this.height-this.radius||this.obstacles.some(o=>Math.hypot(this.x-o.x,this.y-o.y)<o.r+this.radius);
  if(collision){reward-=20;this.collisions=1;this.terminated=true;}
  // The target must enter the forward conveyor mouth while the boat moves forward.
  else if(distance<.5&&bearing<.58&&velocity>.15){reward+=30;this.collected=1;this.terminated=true;}
  this.truncated=!this.terminated&&this.steps>=this.maxSteps;this.done=this.terminated||this.truncated;this.totalReward+=reward;this.route.push([this.x,this.y]);
  this.trace.push({step:this.steps,observation:{...this.observation},action,left:a.left,right:a.right,reward,collection_confirmed:this.collected===1,source:'simulation',control_enabled:false});
  this.observation=this.observe();return{observation:this.observation,reward,terminated:this.terminated,truncated:this.truncated};
 }
 snapshot(){return{seed:this.seed,width:this.width,height:this.height,x:this.x,y:this.y,heading:this.heading,target:{...this.target},obstacles:this.obstacles.map(o=>({...o})),steps:this.steps,max_steps:this.maxSteps,collected:this.collected,collisions:this.collisions,done:this.done,terminated:this.terminated,truncated:this.truncated,observation:this.observation,route:this.route.map(p=>[...p]),action:this.lastAction};}
}
export function greedy(q,state){const offset=state*ACTIONS.length;let a=0;for(let i=1;i<ACTIONS.length;i++)if(q[offset+i]>q[offset+a])a=i;return a;}
export function ruleAction(obs){const mask=obs.obstacle_mask;if(mask&2)return obs.clearance[0]>obs.clearance[2]?3:4;if(!obs.target_visible)return 3;const b=obs.bearing_bin;return b>=9?1:b<=6?2:0;}
export function validatePolicy(p){
 const unit=v=>typeof v==='number'&&Number.isFinite(v)&&v>=0&&v<=1;
 const t=p?.training;
 if(p?.schema!=='warirak.navigation-policy.v1'||p.environment!==ENV_VERSION||p.source!=='simulation'||p.state_count!==STATES||!Array.isArray(p.q_values)||p.q_values.length!==STATES*ACTIONS.length||p.q_values.some(v=>typeof v!=='number'||!Number.isFinite(v))||p.action_names?.join('|')!==ACTIONS.map(a=>a.name).join('|')||!t||!Number.isInteger(t.episodes)||t.episodes<100||t.episodes>20000||!Number.isInteger(t.seed)||t.seed<0||t.seed+t.episodes>2147483647||t.train_seeds?.[0]!==t.seed||t.train_seeds?.[1]!==t.seed+t.episodes-1||p.control_enabled!==false||p.real_world_validated!==false)throw Error('ไฟล์นโยบายไม่ตรงกับสนามฝึกรุ่นนี้');
 if(p.curve&&(!Array.isArray(p.curve)||p.curve.length>200||p.curve.some(c=>!Number.isInteger(c.episode)||c.episode<100||c.episode>t.episodes||!unit(c.success_rate))))throw Error('ข้อมูลกราฟการฝึกไม่ถูกต้อง');
 const e=p.evaluation;if(e){const modes=['learned','rule','random'];if(e.source!=='simulation'||e.environment!==ENV_VERSION||!Number.isInteger(e.seed)||!Number.isInteger(e.episodes)||e.episodes<1||e.episodes>1000||e.seed<=t.train_seeds[1]&&e.seed+e.episodes-1>=t.train_seeds[0]||!Array.isArray(e.results)||e.results.length!==3||e.results.some((r,i)=>r.controller!==modes[i]||r.episodes!==e.episodes||![r.collections,r.collisions,r.timeouts].every(v=>Number.isInteger(v)&&v>=0&&v<=e.episodes)||r.collections+r.collisions+r.timeouts!==e.episodes||!unit(r.success_rate)||!unit(r.collision_rate)||Math.abs(r.success_rate-r.collections/e.episodes)>1e-6||Math.abs(r.collision_rate-r.collisions/e.episodes)>1e-6||!Number.isFinite(r.mean_steps)||r.mean_steps<1||r.mean_steps>320))throw Error('รายงานผลทดสอบนโยบายไม่ถูกต้อง');}
 return p;
}
export function createTrainer({episodes=5000,seed=42}={}){
 if(!Number.isInteger(episodes)||episodes<100||episodes>20000||!Number.isInteger(seed)||seed<0||seed+episodes>2147483647)throw Error('จำนวนรอบต้องอยู่ระหว่าง 100–20,000 และ seed เป็นจำนวนเต็มบวก');
 const random=rng(seed),q=new Float64Array(STATES*ACTIONS.length),curve=[];let completed=0,batchSuccess=0,batchCollision=0,batchReward=0;
 return{get completed(){return completed;},get total(){return episodes;},batch(count=50){
  for(let n=0;n<count&&completed<episodes;n++){
   const env=new PoolEnv(seed+completed),epsilon=.035+.965*Math.max(0,1-completed/(episodes*.85));let obs=env.observation;
   while(!env.done){const action=random()<epsilon?Math.floor(random()*ACTIONS.length):greedy(q,obs.state),result=env.step(action),next=result.observation.state,offset=obs.state*ACTIONS.length+action;
    // A step-limit truncation retains bootstrapping; only a true terminal transition zeroes it.
    const target=result.reward+(result.terminated?0:.97*q[next*ACTIONS.length+greedy(q,next)]);q[offset]+=.12*(target-q[offset]);obs=result.observation;
   }
   completed++;batchSuccess+=env.collected;batchCollision+=env.collisions;batchReward+=env.totalReward;
   if(completed%100===0){curve.push({episode:completed,episodes:100,success_rate:batchSuccess/100,collision_rate:batchCollision/100,mean_reward:batchReward/100});batchSuccess=batchCollision=batchReward=0;}
  }return{completed,total:episodes,curve:curve.slice(-1)};
 },finish(){if(completed!==episodes)throw Error('Training is incomplete');return{schema:'warirak.navigation-policy.v1',environment:ENV_VERSION,source:'simulation',created_at:new Date().toISOString(),state_count:STATES,action_names:ACTIONS.map(a=>a.name),q_values:Array.from(q,x=>Math.round(x*1e6)/1e6),training:{method:'tabular Q-learning',episodes,seed,train_seeds:[seed,seed+episodes-1],alpha:.12,gamma:.97,max_steps:320,observation:'synthetic camera bearing (16 bins + unseen), coarse range, three obstacle sectors',domain_randomization:['spawn','obstacle layout','thrust imbalance','water drift','bearing noise']},curve,real_world_validated:false,control_enabled:false};}};
}
export function evaluatePolicy(policy,{episodes=200,seed=1000000}={}){
 validatePolicy(policy);const [lo,hi]=policy.training.train_seeds;if(seed<=hi&&seed+episodes-1>=lo)throw Error('Evaluation seeds overlap training');
 const results=[];
 for(const mode of['learned','rule','random']){let collected=0,collisions=0,steps=0,timeouts=0;for(let i=0;i<episodes;i++){const env=new PoolEnv(seed+i),random=rng(seed+i+700000);while(!env.done){const a=mode==='learned'?greedy(policy.q_values,env.observation.state):mode==='rule'?ruleAction(env.observation):Math.floor(random()*ACTIONS.length);env.step(a);}collected+=env.collected;collisions+=env.collisions;steps+=env.steps;timeouts+=Number(env.truncated);}
  results.push({controller:mode,episodes,collections:collected,collisions,timeouts,success_rate:collected/episodes,collision_rate:collisions/episodes,mean_steps:steps/episodes});
 }return{schema:'warirak.navigation-evaluation.v1',source:'simulation',environment:ENV_VERSION,seed,episodes,results,real_world_validated:false};
}
