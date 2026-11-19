// New action ownership, same frozen R2 plant/guards/reward/rollout accounting. Research only.
import{rng}from'../frontend/autonomy.js';
import{MissionPoolEnvR2,MISSION_ENV_R2}from'./navigation_mission_env_r2.mjs';
import{runMissionEpisode,missionBaseline,MISSION_FEATURES}from'./navigation_mission_learning.mjs';
import{NAV_ONLY_INTERFACE,NAV_ONLY_FEATURES,NAV_ONLY_MODEL,NAV_ONLY_ACTIONS,NAV_ONLY_STATES,navigationFeatures,encodeNavigation,navigationAllowed,navigationRule}from'./navigation_action_interface.mjs';
const finite=v=>typeof v==='number'&&Number.isFinite(v);
const toNavigation=f=>({...f,schema:NAV_ONLY_FEATURES});
const navMask=list=>{const result=list.filter(a=>a<7);if(!result.length)throw Error('No navigation-only request allowed');return result;};
function validTable(table){return table&&typeof table==='object'&&!Array.isArray(table)&&Object.entries(table).every(([key,row])=>String(Number(key))===key&&Number.isInteger(Number(key))&&Number(key)>=0&&Number(key)<NAV_ONLY_STATES&&Array.isArray(row)&&row.length===7&&row.every(finite));}
export function validateNavigationPolicy(p){
 const t=p?.training;
 if(p?.schema!==NAV_ONLY_MODEL||p.environment!==MISSION_ENV_R2||p.decision_interface!==NAV_ONLY_INTERFACE||p.feature_schema!==NAV_ONLY_FEATURES||p.source!=='simulation'||p.state_count!==NAV_ONLY_STATES||p.action_names?.join('|')!==NAV_ONLY_ACTIONS.join('|')||p.fallback!=='navigation-rules-v1'||!validTable(p.q_table)||!t||!Number.isInteger(t.episodes)||t.episodes<1||!Number.isInteger(t.budget_episodes)||t.budget_episodes<t.episodes||t.budget_episodes>100000||!Number.isInteger(t.seed)||t.seed<0||t.seed+t.budget_episodes>2147483647||t.train_seeds?.[0]!==t.seed||t.train_seeds?.[1]!==t.seed+t.episodes-1||p.control_enabled!==false||p.real_world_validated!==false||p.production_runtime_supported!==false)throw Error('Unsupported navigation-only learned policy');return p;
}
function best(row,allowed){let a=allowed[0];for(const n of allowed)if(row[n]>row[a])a=n;return a;}
export function navigationPolicyController(p){validateNavigationPolicy(p);return(o,prev)=>{const f=navigationFeatures(o,prev),allowed=navigationAllowed(o,f),row=p.q_table[encodeNavigation(f)];return row?best(row,allowed):navigationRule(f,allowed);};}
export function navigationBaseline(kind,legacy){
 const original=missionBaseline(kind,legacy);
 return(o,prev)=>{const f=navigationFeatures(o,prev),allowed=navigationAllowed(o,f),a=original(o,prev);if(a>=7)throw Error('Baseline attempted an operator-only request');return allowed.includes(a)?a:navigationRule(f,allowed);};
}
function trainingConfig({episodes,seed,alpha=.05,gamma=.985,epsilon_floor=.04,epsilon_start=.4}){if(!Number.isInteger(episodes)||episodes<1||episodes>100000||!Number.isInteger(seed)||seed<0||seed+episodes>2147483647||![alpha,gamma,epsilon_floor,epsilon_start].every(v=>finite(v)&&v>0&&v<=1)||epsilon_floor>epsilon_start)throw Error('Invalid navigation-only recipe');return{episodes,seed,alpha,gamma,epsilon_floor,epsilon_start};}
export function createNavigationTrainer(options){
 const config=trainingConfig(options),checkpoint=options.checkpoint,q=new Map();let completed=0,curve=[],batch={n:0,collections:0,collisions:0,assistance:0,reward:0};
 if(checkpoint){const b=checkpoint.batch;if(checkpoint.schema!=='warirak.navigation-only-checkpoint.v1'||JSON.stringify(checkpoint.config)!==JSON.stringify(config)||!Number.isInteger(checkpoint.completed)||checkpoint.completed<0||checkpoint.completed>config.episodes||!validTable(checkpoint.q_table)||!Array.isArray(checkpoint.curve)||!b||!Number.isInteger(b.n)||b.n<0||b.n>99||![b.collections,b.collisions,b.assistance].every(v=>Number.isInteger(v)&&v>=0&&v<=b.n)||!finite(b.reward))throw Error('Navigation-only checkpoint/config mismatch');for(const[k,v]of Object.entries(checkpoint.q_table))q.set(Number(k),Float64Array.from(v));completed=checkpoint.completed;curve=structuredClone(checkpoint.curve);batch=structuredClone(b);}
 const table=()=>Object.fromEntries([...q.entries()].sort((a,b)=>a[0]-b[0]).map(([k,v])=>[k,Array.from(v)]));
 const rowFor=(f,allowed)=>{const id=encodeNavigation(f);if(!q.has(id)){const row=new Float64Array(7);row[navigationRule(f,allowed)]=.2;q.set(id,row);}return q.get(id);};
 return{
  get completed(){return completed;},get budget(){return config.episodes;},
  batch(count=1){for(let n=0;n<count&&completed<config.episodes;n++){
   const ep=completed,env=new MissionPoolEnvR2(config.seed+ep,{profile:ep%4===0?'nominal':'stress'}),random=rng((config.seed^Math.imul(ep+1,0x1a56b9))>>>0),epsilon=config.epsilon_floor+(config.epsilon_start-config.epsilon_floor)*Math.max(0,1-ep/(config.episodes*.85));
   const choose=(o,prev)=>{const f=navigationFeatures(o,prev),allowed=navigationAllowed(o,f),row=rowFor(f,allowed);return random()<epsilon?allowed[Math.floor(random()*allowed.length)]:best(row,allowed);};
   const result=runMissionEpisode(env,choose,({features,allowed,action,reward,nextFeatures,nextAllowed,terminal})=>{if(action>=7||features.schema!==MISSION_FEATURES)throw Error('Operator request leaked into navigation learner');const f=toNavigation(features),nf=toNavigation(nextFeatures),mask=navMask(allowed),nextMask=navMask(nextAllowed),row=rowFor(f,mask),next=rowFor(nf,nextMask),target=reward+(terminal?0:config.gamma*next[best(next,nextMask)]);row[action]+=config.alpha*(target-row[action]);});
   completed++;batch.n++;batch.collections+=result.collections;batch.collisions+=result.collisions;batch.assistance+=Number(result.assistance);batch.reward+=result.reward;
   if(batch.n===100||completed===config.episodes){curve.push({episode:completed,episodes:batch.n,success_rate:batch.collections/batch.n,collision_rate:batch.collisions/batch.n,assistance_rate:batch.assistance/batch.n,mean_reward:batch.reward/batch.n});batch={n:0,collections:0,collisions:0,assistance:0,reward:0};}
  }return{completed,budget:config.episodes,visited_states:q.size};},
  checkpoint(){return{schema:'warirak.navigation-only-checkpoint.v1',config,completed,q_table:table(),curve:structuredClone(curve),batch:structuredClone(batch)};},
  policy(){return validateNavigationPolicy({schema:NAV_ONLY_MODEL,environment:MISSION_ENV_R2,decision_interface:NAV_ONLY_INTERFACE,feature_schema:NAV_ONLY_FEATURES,source:'simulation',state_count:NAV_ONLY_STATES,action_names:[...NAV_ONLY_ACTIONS],q_table:table(),fallback:'navigation-rules-v1',training:{method:'sparse tabular Q-learning;navigation-only7requests;operator assistance owned by independent supervisor/operator',episodes:completed,budget_episodes:config.episodes,seed:config.seed,train_seeds:[config.seed,config.seed+completed-1],alpha:config.alpha,gamma:config.gamma,epsilon_floor:config.epsilon_floor,epsilon_start:config.epsilon_start},curve:structuredClone(curve),independent_supervisor_preserved:true,experimental:true,production_runtime_supported:false,control_enabled:false,real_world_validated:false});}
 };
}
