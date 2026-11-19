// Separately versioned, synthetic environment. No motor/network/serial transport.
import {rng} from '../frontend/autonomy.js';
export const MEMORY_ENV='warirak-pool-memory-v3';
export const MEMORY_SCHEMA='warirak.navigation-memory-policy.v1';
export const MEMORY_ACTIONS=[{name:'STOP',left:0,right:0},{name:'FORWARD',left:.65,right:.65},{name:'TURN_LEFT',left:.25,right:.65},{name:'TURN_RIGHT',left:.65,right:.25},{name:'PIVOT_LEFT',left:-.3,right:.3},{name:'PIVOT_RIGHT',left:.3,right:-.3}];
export const MEMORY_STATES=20*3*9*36;
const clamp=(x,a,b)=>Math.max(a,Math.min(b,x)),wrap=x=>Math.atan2(Math.sin(x),Math.cos(x));
export function encodeMemory({bearingState,rangeBin,obstacleMask,previousCommands}){
 if(!Number.isInteger(bearingState)||bearingState<0||bearingState>=20||!Number.isInteger(rangeBin)||rangeBin<0||rangeBin>2||!Number.isInteger(obstacleMask)||obstacleMask<0||obstacleMask>8||!Array.isArray(previousCommands)||previousCommands.length!==2||previousCommands.some(x=>!Number.isInteger(x)||x<0||x>5))throw Error('Invalid memory observation');
 return((bearingState*3+rangeBin)*9+obstacleMask)*36+previousCommands[0]*6+previousCommands[1];
}
export function decodeMemory(state){if(!Number.isInteger(state)||state<0||state>=MEMORY_STATES)throw Error('Invalid state');const history=state%36,base=Math.floor(state/36),mask=base%9,rest=Math.floor(base/9);return{bearingState:Math.floor(rest/3),rangeBin:rest%3,obstacleMask:mask,previousCommands:[Math.floor(history/6),history%6]};}
export function sixGreedy(q,state){const offset=state*6;let action=0;for(let i=1;i<6;i++)if(q[offset+i]>q[offset+action])action=i;return action;}
export function validateMemoryPolicy(policy){
 if(policy?.schema!==MEMORY_SCHEMA||policy.environment!==MEMORY_ENV||policy.source!=='simulation'||policy.state_count!==MEMORY_STATES||policy.action_names?.join('|')!==MEMORY_ACTIONS.map(a=>a.name).join('|')||!Array.isArray(policy.q_values)||policy.q_values.length!==MEMORY_STATES*6||policy.q_values.some(x=>!Number.isFinite(x))||policy.control_enabled!==false||policy.real_world_validated!==false)throw Error('Unsupported memory policy; the old Q-table is not interchangeable');
 const t=policy.training;if(!t||!Number.isInteger(t.episodes)||t.episodes<100||t.episodes>100000||!Number.isInteger(t.seed)||t.seed<0||t.seed+t.episodes>2147483647||t.train_seeds?.[0]!==t.seed||t.train_seeds?.[1]!==t.seed+t.episodes-1)throw Error('Invalid memory training range');return policy;
}
export class MemoryPoolEnv{
 constructor(seed=1,{profile='stress',record=false}={}){if(!['nominal','stress'].includes(profile))throw Error('Unknown profile');this.profile=profile;this.record=record;this.reset(seed);}
 reset(seed=1){
  if(!Number.isInteger(seed)||seed<0||seed>2147483647)throw Error('Invalid seed');this.seed=seed;const random=rng(seed),domain=rng((seed^0x24ac7d)>>>0);this.noise=rng((seed^0x3781ad)>>>0);
  this.width=10;this.height=6;this.radius=.19;this.steps=0;this.maxSteps=320;this.done=false;this.terminated=false;this.truncated=false;this.collected=0;this.collisions=0;this.totalReward=0;this.supervisorStops=0;this.receiverStops=0;this.explicitStops=0;
  this.obstacles=Array.from({length:3},()=>({x:2+random()*6,y:1+random()*4,r:.25+random()*.3}));
  const spawn=()=>{for(let i=0;i<500;i++){const p={x:.7+random()*8.6,y:.7+random()*4.6};if(this.obstacles.every(o=>Math.hypot(p.x-o.x,p.y-o.y)>o.r+.8))return p;}throw Error('Unable to generate a valid scene');};
  Object.assign(this,spawn());this.heading=random()*Math.PI*2;for(let i=0;i<500;i++){this.target=spawn();if(Math.hypot(this.target.x-this.x,this.target.y-this.y)>=2.2)break;if(i===499)throw Error('Unable to generate target');}this.target.class_id=random()<.65?0:1;
  const stress=this.profile==='stress',gain=stress?.2:.08,drift=stress?.16:.045;this.leftGain=1-gain+domain()*gain*2;this.rightGain=1-gain+domain()*gain*2;this.drift={x:(domain()-.5)*drift,y:(domain()-.5)*drift};
  this.domain={delay:stress?Math.floor(domain()*3):0,bearingNoise:stress?.16:.02,rangeNoise:stress?.25:0,clearanceNoise:stress?.1:0,targetDropout:stress?.08:0,sensorDropout:stress?.02:0};
  this.queue=[];this.previousCommands=[0,0];this.lastSeen=null;this.trace=[];this.route=[[this.x,this.y]];this.observation=this._sampleObservation();return this.observe();
 }
 ray(angle){const dx=Math.cos(angle),dy=Math.sin(angle),rad=this.radius;let best=1.5;for(const[t,ok]of[[(rad-this.x)/dx,dx<0],[(this.width-rad-this.x)/dx,dx>0],[(rad-this.y)/dy,dy<0],[(this.height-rad-this.y)/dy,dy>0]])if(ok&&t>=0)best=Math.min(best,t);for(const o of this.obstacles){const ox=this.x-o.x,oy=this.y-o.y,b=ox*dx+oy*dy,c=ox*ox+oy*oy-(o.r+rad)**2,d=b*b-c;if(d>=0){const t=-b-Math.sqrt(d);if(t>=0)best=Math.min(best,t);}}return Math.max(0,best);}
 _sampleObservation(){
  const d=this.domain,random=this.noise,distance=Math.hypot(this.target.x-this.x,this.target.y-this.y),bearing=wrap(Math.atan2(this.target.y-this.y,this.target.x-this.x)-this.heading),visible=Math.abs(bearing)<Math.PI*.48&&distance<4.8&&random()>=d.targetDropout;
  const noisyBearing=clamp(bearing+(random()-.5)*2*d.bearingNoise,-Math.PI,Math.PI),currentBin=visible?clamp(Math.floor((noisyBearing+Math.PI)/(2*Math.PI)*16),0,15):16;
  if(visible)this.lastSeen={step:this.steps,side:noisyBearing>.13?1:noisyBearing<-.13?-1:0};const age=this.lastSeen?this.steps-this.lastSeen.step:null,recent=!visible&&age!==null&&age<=2;
  const bearingState=visible?currentBin:recent?17+this.lastSeen.side:19,measuredRange=visible?Math.max(0,distance+(random()-.5)*2*d.rangeNoise):null,rangeBin=visible?(measuredRange<.8?0:measuredRange<2?1:2):2;
  const valid=random()>=d.sensorDropout,clearance=valid?[.65,0,-.65].map(a=>clamp(this.ray(this.heading+a)+(random()-.5)*2*d.clearanceNoise,0,1.5)):[null,null,null];let mask=valid?0:8;if(valid)clearance.forEach((v,i)=>{if(v<.65)mask|=1<<i;});
  const features={bearingState,rangeBin,obstacleMask:mask,previousCommands:[...this.previousCommands]};
  return{schema:'warirak.memory-observation.v1',source:'simulation',state:encodeMemory(features),bearing_state:bearingState,distance_bin:rangeBin,target_visible:visible,last_seen_side:recent?this.lastSeen.side:null,target_age_steps:age===null?null:Math.min(3,age),sensor_valid:valid,clearance,obstacle_mask:mask,previous_commands:[...this.previousCommands],legacy_state:valid?((currentBin*3+rangeBin)*8+mask):null};
 }
 observe(){return structuredClone(this.observation);}
 supervise(action){const o=this.observation;if(action===0)return{issued:0,reason:'explicit_stop'};if(!o.sensor_valid)return{issued:0,reason:'sensor_invalid'};if(Math.min(...o.clearance)<.35)return{issued:0,reason:'obstacle_stop'};const a=MEMORY_ACTIONS[action],yaw=a.right-a.left;if(a.left+a.right>0&&o.clearance[1]<.65)return{issued:0,reason:'forward_clearance'};if(yaw>0&&o.clearance[0]<.65||yaw<0&&o.clearance[2]<.65)return{issued:0,reason:'turn_clearance'};return{issued:action,reason:'clear'};}
 step(action){
  if(!Number.isInteger(action)||!MEMORY_ACTIONS[action])throw Error('Unknown memory action');if(this.done)return{observation:this.observation,reward:0,terminated:this.terminated,truncated:this.truncated};const before=Math.hypot(this.target.x-this.x,this.target.y-this.y),prior=this.observation,guard=this.supervise(action);let applied=0;
  if(guard.issued===0)this.queue=[];else{this.queue.push(guard.issued);if(this.queue.length>this.domain.delay)applied=this.queue.shift();}
  const receiver=this.supervise(applied);if(applied!==0&&receiver.issued===0){applied=0;this.queue=[];this.receiverStops++;}
  if(action===0)this.explicitStops++;else if(guard.issued===0)this.supervisorStops++;this.previousCommands=[this.previousCommands[1],guard.issued];
  const a=MEMORY_ACTIONS[applied],left=a.left*this.leftGain,right=a.right*this.rightGain,velocity=(left+right)/2,dt=.3;
  this.heading=wrap(this.heading+(right-left)/.4*dt);this.x+=(Math.cos(this.heading)*velocity+this.drift.x)*dt;this.y+=(Math.sin(this.heading)*velocity+this.drift.y)*dt;this.steps++;
  const distance=Math.hypot(this.target.x-this.x,this.target.y-this.y),bearing=Math.abs(wrap(Math.atan2(this.target.y-this.y,this.target.x-this.x)-this.heading));let reward=(before-distance)*3-.045-(action===0?.015:action>=4?.02:0)-(guard.issued!==action?.015:0);
  const collision=this.x<this.radius||this.x>this.width-this.radius||this.y<this.radius||this.y>this.height-this.radius||this.obstacles.some(o=>Math.hypot(this.x-o.x,this.y-o.y)<o.r+this.radius);
  if(collision){this.collisions=1;this.terminated=true;reward-=30;}else if(distance<.5&&bearing<.58&&velocity>.15){this.collected=1;this.terminated=true;reward+=30;}
  this.truncated=!this.terminated&&this.steps>=this.maxSteps;this.done=this.terminated||this.truncated;this.totalReward+=reward;
  if(this.record){this.route.push([this.x,this.y]);this.trace.push({step:this.steps,observation:structuredClone(prior),requested_action:action,issued_action:guard.issued,applied_action:applied,supervisor_reason:guard.reason,receiver_reason:receiver.reason,reward,source:'simulation',control_enabled:false});}
  this.observation=this._sampleObservation();return{observation:this.observation,reward,terminated:this.terminated,truncated:this.truncated};
 }
 snapshot(){return{seed:this.seed,profile:this.profile,x:this.x,y:this.y,heading:this.heading,steps:this.steps,collected:this.collected,collisions:this.collisions,done:this.done,queue:[...this.queue],observation:this.observe(),supervisor_stops:this.supervisorStops,receiver_stops:this.receiverStops,explicit_stops:this.explicitStops};}
}
