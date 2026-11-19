// Research learner/adapters for the explicitly synthetic R2 environment, never motor transport.
import {rng,greedy as legacyGreedy,validatePolicy as validateLegacy} from '../frontend/autonomy.js';
import {MissionPoolEnvR2,MISSION_ENV_R2,MISSION_ACTIONS_R2,missionRequestR2} from './navigation_mission_env_r2.mjs';
export const MISSION_POLICY='warirak.mission-q-policy.v1';
export const MISSION_FEATURES='warirak.mission-features.v1';
export const RADICES=[17,3,9,3,5,4,8];
export const MISSION_STATE_COUNT=RADICES.reduce((a,b)=>a*b,1);
const finite=x=>typeof x==='number'&&Number.isFinite(x);
const assistModes=new Set(['FAULT_STOP','HOLD_UNAVAILABLE','RECOVERY_REQUIRED','ACTUATION_UNAVAILABLE','PROGRESS_UNCERTAIN']);
const fresh=(t,now)=>finite(t)&&now-t>=0&&now-t<=300;

export function missionFeatures(o,previousAction=0){
 if(o?.schema!=='warirak.mission-sim-observation.v2'||o.environment!==MISSION_ENV_R2||o.source!=='simulation'||o.control_enabled!==false||!finite(o.timestamp_unix_ms)||!Number.isInteger(previousAction)||previousAction<0||previousAction>7)throw Error('Unsupported mission observation/history');
 const now=o.timestamp_unix_ms,s=o.sensors,p=o.pose,m=o.motion,c=s?.clearance_m,r=s?.range_evidence;
 const rangeValid=s?.source==='simulation'&&fresh(s.timestamp_unix_ms,now)&&r?.status==='fresh'&&fresh(r.captured_at_ms,now)&&Array.isArray(c)&&c.length===8&&c.every(v=>v===null||finite(v)&&v>=0&&v<=1.5)&&[c[0],c[1],c[7]].every(finite);
 const poseValid=p?.source==='simulation'&&p.schema==='warirak.sim-pose.v1'&&p.method==='simulation_truth'&&p.frame==='pool_fixed'&&p.units==='m,rad'&&p.calibrated===true&&fresh(p.timestamp_unix_ms,now)&&[p.x_m,p.y_m,p.heading_rad,p.position_std_m,p.confidence].every(finite)&&p.confidence>=.8&&p.confidence<=1&&p.position_std_m>=0&&p.position_std_m<=.05&&p.x_m>=-.1&&p.x_m<=10.1&&p.y_m>=-.1&&p.y_m<=6.1&&Math.abs(p.heading_rad)<=Math.PI;
 const motionValid=m?.source==='simulation'&&m.schema==='warirak.sim-motion.v1'&&m.method==='simulation_position_difference'&&m.frame==='pool_fixed'&&m.units==='m/s,rad/s'&&m.calibrated===true&&fresh(m.timestamp_unix_ms,now)&&[m.vx_mps,m.vy_mps,m.yaw_rate_rps,m.speed_std_mps,m.confidence].every(finite)&&m.confidence>=.8&&m.confidence<=1&&m.speed_std_mps>=0&&m.speed_std_mps<=.015&&Math.hypot(m.vx_mps,m.vy_mps)<=3&&Math.abs(m.yaw_rate_rps)<=10;
 let obstacleMask=rangeValid?0:8;if(rangeValid)[c[1],c[0],c[7]].forEach((v,i)=>{if(v<.65)obstacleMask|=1<<i;});
 const target=o.target,visible=target?.visible===true&&finite(target.bearing_rad)&&Math.abs(target.bearing_rad)<=Math.PI&&finite(target.range_m)&&target.range_m>=0;
 const bearing=visible?Math.max(0,Math.min(15,Math.floor((target.bearing_rad+Math.PI)/(2*Math.PI)*16))):16;
 const distance=visible?(target.range_m<.8?0:target.range_m<2?1:2):2;
 let hold=0;if(rangeValid&&poseValid&&motionValid&&c.every(v=>finite(v)&&v>=.65))hold=Math.min(...c)<.85?2:1;
 let mode=0;if(s?.armed!==true||s?.manual_override!==false)mode=4;else if(assistModes.has(o.mission?.mode)||['invalid','stale'].includes(r?.status))mode=3;else if(o.mission?.mode==='HOLD')mode=1;else if(o.mission?.mode==='WAIT_RANGE_UPDATE'||o.mission?.mode==='WATCHDOG_STOP')mode=2;
 const along=poseValid&&motionValid?m.vx_mps*Math.cos(p.heading_rad)+m.vy_mps*Math.sin(p.heading_rad):null;
 const velocity=along===null?3:along<-.04?0:along>.04?2:1;
 return{schema:MISSION_FEATURES,bearing,distance,obstacleMask,hold,mode,velocity,previousAction};
}
export function encodeMission(f){
 if(f?.schema!==MISSION_FEATURES)throw Error('Wrong feature schema');const values=[f.bearing,f.distance,f.obstacleMask,f.hold,f.mode,f.velocity,f.previousAction];
 if(values.some((v,i)=>!Number.isInteger(v)||v<0||v>=RADICES[i]))throw Error('Invalid mission features');return values.reduce((n,v,i)=>n*RADICES[i]+v,0);
}
export function decodeMission(id){if(!Number.isInteger(id)||id<0||id>=MISSION_STATE_COUNT)throw Error('Invalid mission state');const values=Array(RADICES.length);for(let i=RADICES.length-1;i>=0;i--){values[i]=id%RADICES[i];id=Math.floor(id/RADICES[i]);}return{schema:MISSION_FEATURES,...Object.fromEntries(['bearing','distance','obstacleMask','hold','mode','velocity','previousAction'].map((k,i)=>[k,values[i]]))};}
export function missionAllowed(o,features=missionFeatures(o)){
 const f=features,c=o.sensors?.clearance_m;
 if(o.sensors?.armed!==true||o.sensors?.manual_override!==false||assistModes.has(o.mission?.mode))return[0];
 // Preserve the REQUESTED intent across missing data so the independent R2 guard emits WAIT/fault.
 // This never authorizes thrust: R2 still zeros/clears the actual command and requires a new request.
 if(f.obstacleMask===8)return[f.previousAction>0?f.previousAction:0];
 if(f.mode>=3||!Array.isArray(c)||c.some(v=>finite(v)&&v<.35))return[0];
 const allowed=[0,7],front=Math.min(c[0],c[1],c[7])>=.65,sides=[c[2],c[6]].every(v=>finite(v)&&v>=.65);
 if(front)allowed.push(1);if(front&&sides)allowed.push(2,3);if(sides)allowed.push(4,5);if(f.hold)allowed.push(6);return allowed.sort((a,b)=>a-b);
}
export function missionRule(f){
 if(f.mode>=3||f.obstacleMask===8)return 0;
 if(f.hold===2&&(f.bearing===16||f.mode===1||f.velocity===0))return 6;
 if(f.obstacleMask&2)return f.obstacleMask&1?5:4;
 if(f.bearing===16)return 4;return f.bearing>=9?2:f.bearing<=6?3:1;
}
function safeFallback(f,allowed){const preferred=missionRule(f);return allowed.includes(preferred)?preferred:allowed.includes(0)?0:allowed[0];}
export function missionBaseline(kind,legacy){
 if(!['legacy_mapped','rules_with_hold'].includes(kind))throw Error('Unknown baseline');if(kind==='legacy_mapped')validateLegacy(legacy);
 return(o,previousAction)=>{const f=missionFeatures(o,previousAction),allowed=missionAllowed(o,f);if(kind==='rules_with_hold'||f.obstacleMask===8||f.mode>=3)return safeFallback(f,allowed);
  const oldState=(f.bearing*3+f.distance)*8+f.obstacleMask,action=legacyGreedy(legacy.q_values,oldState)+1;return allowed.includes(action)?action:safeFallback(f,allowed);
 };
}
function validTable(table){return table&&typeof table==='object'&&!Array.isArray(table)&&Object.entries(table).every(([key,row])=>String(Number(key))===key&&Number.isInteger(Number(key))&&Number(key)>=0&&Number(key)<MISSION_STATE_COUNT&&Array.isArray(row)&&row.length===8&&row.every(finite));}
export function validateMissionPolicy(p){
 const t=p?.training;
 if(p?.schema!==MISSION_POLICY||p.environment!==MISSION_ENV_R2||p.source!=='simulation'||p.feature_schema!==MISSION_FEATURES||p.state_count!==MISSION_STATE_COUNT||p.action_names?.join('|')!==MISSION_ACTIONS_R2.join('|')||p.fallback!=='mission-rules-v1'||!validTable(p.q_table)||!t||!Number.isInteger(t.episodes)||t.episodes<1||!Number.isInteger(t.budget_episodes)||t.budget_episodes<t.episodes||t.budget_episodes>100000||!Number.isInteger(t.seed)||t.seed<0||t.seed+t.budget_episodes>2147483647||t.train_seeds?.[0]!==t.seed||t.train_seeds?.[1]!==t.seed+t.episodes-1||p.control_enabled!==false||p.real_world_validated!==false||p.production_runtime_supported!==false)throw Error('Unsupported mission learned policy');return p;
}
export function missionPolicyController(policy){validateMissionPolicy(policy);return(o,previousAction)=>{const f=missionFeatures(o,previousAction),allowed=missionAllowed(o,f),row=policy.q_table[encodeMission(f)];if(!row)return safeFallback(f,allowed);let best=allowed[0];for(const a of allowed)if(row[a]>row[best])best=a;return best;};}
function addObservationMetrics(stats,o){
 const status=o.sensors?.range_evidence?.status,mode=o.mission?.mode;
 if(status!=='fresh')stats.range_wait_steps++;
 if(['stale','invalid'].includes(status)||mode==='ACTUATION_UNAVAILABLE')stats.hard_unavailable=true;
 if(assistModes.has(mode))stats.assistance=true;
 if(mode==='PROGRESS_UNCERTAIN')stats.progress_uncertain=true;
}
export function runMissionEpisode(env,controller,onTransition=()=>{}){
 const stats={steps:0,reward:0,range_wait_steps:0,hard_unavailable:false,assistance:false,progress_uncertain:false,source:'simulation',fixture_used:env.fixtureUsed};let previousAction=0;
 while(!env.done){
  const o=env.observe(),before=Math.hypot(env.target.x-env.x,env.target.y-env.y),f=missionFeatures(o,previousAction),allowed=missionAllowed(o,f),a=controller(o,previousAction,allowed);
  if(!Number.isInteger(a)||!allowed.includes(a))throw Error('Controller selected action outside common observation-based mask');
  addObservationMetrics(stats,o);env.step(missionRequestR2(env.steps,env.now(),MISSION_ACTIONS_R2[a]));
  const next=env.observe(),after=Math.hypot(env.target.x-env.x,env.target.y-env.y),newAssist=!stats.assistance&&assistModes.has(next.mission?.mode);
  // World geometry is only a training reward/terminal measurement; it never enters policy features.
  const reward=3*(before-after)-.015+(env.collected?40:0)-(env.collisions?30:0)-(newAssist?10:0);
  const nextFeatures=missionFeatures(next,a),nextAllowed=missionAllowed(next,nextFeatures);
  onTransition({features:f,allowed,action:a,reward,nextFeatures,nextAllowed,terminal:!!(env.collected||env.collisions)});
  stats.steps++;stats.reward+=reward;addObservationMetrics(stats,next);previousAction=a;
 }
 // Do not stop a rollout at assistance: the plant/current runs to collision, collection or full timeout.
 return{...stats,collections:env.collected,collisions:env.collisions,timeouts:Number(env.truncated),control_enabled:false};
}
function trainingConfig({episodes,seed,alpha=.05,gamma=.985,epsilon_floor=.04,epsilon_start=.4}){if(!Number.isInteger(episodes)||episodes<1||episodes>100000||!Number.isInteger(seed)||seed<0||seed+episodes>2147483647||![alpha,gamma,epsilon_floor,epsilon_start].every(x=>finite(x)&&x>0&&x<=1)||epsilon_floor>epsilon_start)throw Error('Invalid training configuration');return{episodes,seed,alpha,gamma,epsilon_floor,epsilon_start};}
export function createMissionTrainer(options){
 const {checkpoint=null}=options,config=trainingConfig(options),q=new Map();let completed=0,curve=[],batch={n:0,collections:0,collisions:0,assistance:0,reward:0};
 if(checkpoint){const b=checkpoint.batch;if(checkpoint.schema!=='warirak.mission-checkpoint.v1'||JSON.stringify(checkpoint.config)!==JSON.stringify(config)||!Number.isInteger(checkpoint.completed)||checkpoint.completed<0||checkpoint.completed>config.episodes||!validTable(checkpoint.q_table)||!Array.isArray(checkpoint.curve)||!b||!Number.isInteger(b.n)||b.n<0||b.n>99||![b.collections,b.collisions,b.assistance].every(v=>Number.isInteger(v)&&v>=0&&v<=b.n)||!finite(b.reward))throw Error('Checkpoint/config mismatch');for(const [k,v]of Object.entries(checkpoint.q_table))q.set(Number(k),Float64Array.from(v));completed=checkpoint.completed;curve=structuredClone(checkpoint.curve);batch=structuredClone(checkpoint.batch);}
 const table=()=>Object.fromEntries([...q.entries()].sort((a,b)=>a[0]-b[0]).map(([k,v])=>[k,Array.from(v)]));
 function rowFor(f,allowed){const state=encodeMission(f);if(!q.has(state)){const row=new Float64Array(8);row[safeFallback(f,allowed)]=.2;q.set(state,row);}return q.get(state);}
 function best(row,allowed){let a=allowed[0];for(const n of allowed)if(row[n]>row[a])a=n;return a;}
 return{
  get completed(){return completed;},get budget(){return config.episodes;},
  batch(count=1){for(let n=0;n<count&&completed<config.episodes;n++){
   const ep=completed,env=new MissionPoolEnvR2(config.seed+ep,{profile:ep%4===0?'nominal':'stress'}),random=rng((config.seed^Math.imul(ep+1,0x1a56b9))>>>0),epsilon=config.epsilon_floor+(config.epsilon_start-config.epsilon_floor)*Math.max(0,1-ep/(config.episodes*.85));
   const controller=(o,prev,allowed)=>{const row=rowFor(missionFeatures(o,prev),allowed);return random()<epsilon?allowed[Math.floor(random()*allowed.length)]:best(row,allowed);};
   const result=runMissionEpisode(env,controller,({features,allowed,action,reward,nextFeatures,nextAllowed,terminal})=>{const row=rowFor(features,allowed);const next=rowFor(nextFeatures,nextAllowed);const target=reward+(terminal?0:config.gamma*next[best(next,nextAllowed)]);row[action]+=config.alpha*(target-row[action]);});
   completed++;batch.n++;batch.collections+=result.collections;batch.collisions+=result.collisions;batch.assistance+=Number(result.assistance);batch.reward+=result.reward;
   if(batch.n===100||completed===config.episodes){curve.push({episode:completed,episodes:batch.n,success_rate:batch.collections/batch.n,collision_rate:batch.collisions/batch.n,assistance_rate:batch.assistance/batch.n,mean_reward:batch.reward/batch.n});batch={n:0,collections:0,collisions:0,assistance:0,reward:0};}
  }return{completed,budget:config.episodes,visited_states:q.size};},
  checkpoint(){return{schema:'warirak.mission-checkpoint.v1',config,completed,q_table:table(),curve:structuredClone(curve),batch:structuredClone(batch)};},
  policy(){return validateMissionPolicy({schema:MISSION_POLICY,environment:MISSION_ENV_R2,source:'simulation',feature_schema:MISSION_FEATURES,state_count:MISSION_STATE_COUNT,action_names:[...MISSION_ACTIONS_R2],q_table:table(),fallback:'mission-rules-v1',training:{method:'sparse tabular Q-learning initialized from fixed rules;25%nominal75%stress;observation-only masks',episodes:completed,budget_episodes:config.episodes,seed:config.seed,train_seeds:[config.seed,config.seed+completed-1],alpha:config.alpha,gamma:config.gamma,epsilon_floor:config.epsilon_floor,epsilon_start:config.epsilon_start},curve:structuredClone(curve),experimental:true,production_runtime_supported:false,control_enabled:false,real_world_validated:false});}
 };
}
export function evaluateMission(controller,{profile,seed,episodes,excludedRanges=[]}={}){
 if(typeof controller!=='function'||!['nominal','stress'].includes(profile)||!Number.isInteger(seed)||seed<0||!Number.isInteger(episodes)||episodes<1||episodes>2000||seed+episodes>2147483647||excludedRanges.some(([lo,hi])=>seed<=hi&&seed+episodes-1>=lo))throw Error('Invalid/overlapping mission evaluation partition');
 const total={collections:0,collisions:0,timeouts:0,assistance_episodes:0,hard_unavailable_episodes:0,progress_uncertain_episodes:0,transport_latency_over_ttl_episodes:0,steps:0,range_wait_steps:0};
 for(let i=0;i<episodes;i++){const env=new MissionPoolEnvR2(seed+i,{profile});if(env.fixtureUsed)throw Error('Development fixtures forbidden in evaluation');total.transport_latency_over_ttl_episodes+=Number(env.delayTicks*100>=400);const r=runMissionEpisode(env,controller);for(const k of ['collections','collisions','timeouts','steps','range_wait_steps'])total[k]+=r[k];total.assistance_episodes+=Number(r.assistance);total.hard_unavailable_episodes+=Number(r.hard_unavailable);total.progress_uncertain_episodes+=Number(r.progress_uncertain);}
 if(total.collections+total.collisions+total.timeouts!==episodes)throw Error('Outcome accounting lost an episode');
 return{schema:'warirak.mission-evaluation.v1',environment:MISSION_ENV_R2,source:'simulation',profile,seed,episodes,...total,success_rate:total.collections/episodes,collision_rate:total.collisions/episodes,timeout_rate:total.timeouts/episodes,assistance_rate:total.assistance_episodes/episodes,hard_unavailable_rate:total.hard_unavailable_episodes/episodes,mean_steps:total.steps/episodes,range_wait_observation_fraction:total.range_wait_steps/(2*total.steps),all_fault_cases_in_denominator:true,continues_physics_after_assistance:true,control_enabled:false,real_world_validated:false};
}
export function missionResearchGate(baselines,candidate,config){
 const checks=[];
 for(const profile of ['nominal','stress']){
  const refs=Object.values(baselines).map(b=>b[profile]),c=candidate[profile],g=config.research[profile];
  if(!g||Object.values(g).some(v=>!finite(v)||v<0||v>1)||!['min_success','max_collision','max_timeout','max_assistance','max_hard_unavailable','max_range_wait_fraction'].every(k=>finite(g[k]))||!['min_stress_success_gain','max_nominal_success_drop','max_collision_increase'].every(k=>finite(config[k])&&config[k]>=0&&config[k]<=1))throw Error('Invalid mission selection gates');
  for(const m of [...refs,c])if(!m||['success_rate','collision_rate','timeout_rate','assistance_rate','hard_unavailable_rate','range_wait_observation_fraction'].some(k=>!finite(m[k])||m[k]<0||m[k]>1))throw Error('Incomplete mission gate metrics');
  const add=(name,passed)=>checks.push({profile,name,passed});
  add('absolute_success',c.success_rate>=g.min_success);add('absolute_collision',c.collision_rate<=g.max_collision);add('absolute_timeout',c.timeout_rate<=g.max_timeout);add('absolute_assistance',c.assistance_rate<=g.max_assistance);add('absolute_unavailability',c.hard_unavailable_rate<=g.max_hard_unavailable);add('range_wait_fraction',c.range_wait_observation_fraction<=g.max_range_wait_fraction);
  const success=Math.max(...refs.map(r=>r.success_rate)),collision=Math.min(...refs.map(r=>r.collision_rate));
  add('best_reference_success',c.success_rate>=success+(profile==='stress'?config.min_stress_success_gain:-config.max_nominal_success_drop));
  add('lowest_reference_collision',c.collision_rate<=collision+config.max_collision_increase);
 }
 return{eligible:checks.every(c=>c.passed),checks,test_used_for_selection:false,research_only:true,production_ready:false};
}
export function assertMissionPartitions(config){
 const ranges=[['train',config.training.seed,config.training.episodes],...['validation','test'].flatMap(group=>['nominal','stress'].map(profile=>[group+'_'+profile,config[group][profile+'_seed'],config[group].episodes_per_profile]))];
 if(ranges.some(([,seed,n])=>!Number.isInteger(seed)||seed<0||!Number.isInteger(n)||n<1||seed+n>2147483647))throw Error('Invalid protocol seed range');
 for(let i=0;i<ranges.length;i++)for(let j=i+1;j<ranges.length;j++)if(ranges[i][1]<=ranges[j][1]+ranges[j][2]-1&&ranges[i][1]+ranges[i][2]-1>=ranges[j][1])throw Error('Protocol partitions overlap');
 return ranges.map(([name,seed,n])=>({name,range:[seed,seed+n-1]}));
}
