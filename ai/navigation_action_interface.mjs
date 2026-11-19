// Explicit decision ownership for a future navigation-only learner. No training or actuator I/O.
import{MISSION_ACTIONS_R2,MISSION_ENV_R2,missionRequestR2}from'./navigation_mission_env_r2.mjs';
import{missionFeatures,MISSION_FEATURES,missionAllowed,missionRule}from'./navigation_mission_learning.mjs';
export const NAV_ONLY_INTERFACE='warirak.navigation-only-interface.v1';
export const NAV_ONLY_FEATURES='warirak.navigation-only-features.v1';
export const NAV_ONLY_MODEL='warirak.navigation-only-q-policy.v1';
export const NAV_ONLY_ACTIONS=Object.freeze(MISSION_ACTIONS_R2.slice(0,7));
export const NAV_ONLY_RADICES=[17,3,9,3,5,4,7];
export const NAV_ONLY_STATES=NAV_ONLY_RADICES.reduce((n,v)=>n*v,1);
const finite=v=>typeof v==='number'&&Number.isFinite(v);

export function navigationFeatures(observation,previousNavigationAction=0){
 if(!Number.isInteger(previousNavigationAction)||previousNavigationAction<0||previousNavigationAction>=7)throw Error('Operator assistance is not navigation action history');
 return{...missionFeatures(observation,previousNavigationAction),schema:NAV_ONLY_FEATURES};
}
export function encodeNavigation(f){
 const values=[f?.bearing,f?.distance,f?.obstacleMask,f?.hold,f?.mode,f?.velocity,f?.previousAction];
 if(f?.schema!==NAV_ONLY_FEATURES||values.some((v,i)=>!Number.isInteger(v)||v<0||v>=NAV_ONLY_RADICES[i]))throw Error('Wrong navigation-only feature schema/state');
 return values.reduce((id,v,i)=>id*NAV_ONLY_RADICES[i]+v,0);
}
export function decodeNavigation(id){
 if(!Number.isInteger(id)||id<0||id>=NAV_ONLY_STATES)throw Error('Invalid navigation-only state');
 const values=[];for(let i=NAV_ONLY_RADICES.length-1;i>=0;i--){values[i]=id%NAV_ONLY_RADICES[i];id=Math.floor(id/NAV_ONLY_RADICES[i]);}
 return{schema:NAV_ONLY_FEATURES,...Object.fromEntries(['bearing','distance','obstacleMask','hold','mode','velocity','previousAction'].map((k,i)=>[k,values[i]]))};
}
export function navigationAllowed(observation,features=navigationFeatures(observation)){
 encodeNavigation(features);
 const result=missionAllowed(observation,{...features,schema:MISSION_FEATURES}).filter(a=>a<7);
 if(!result.length)throw Error('Unexpected operator-only action in navigation history');return result;
}
export function navigationRule(features,allowed){
 encodeNavigation(features);const preferred=missionRule({...features,schema:MISSION_FEATURES});
 return allowed.includes(preferred)?preferred:allowed.includes(0)?0:allowed[0];
}
export function navigationIntent(action,sequence,atMs,ttlMs=400){
 if(!Number.isInteger(action)||action<0||action>=7||!Number.isInteger(sequence)||sequence<0||!finite(atMs)||atMs<=0||!finite(ttlMs)||ttlMs<=0||ttlMs>400)throw Error('Invalid navigation-only intent');
 return{schema:'warirak.navigation-intent.v1',decision_interface:NAV_ONLY_INTERFACE,plant_environment:MISSION_ENV_R2,source:'simulation',action,action_name:NAV_ONLY_ACTIONS[action],sequence,issued_at_ms:atMs,valid_until_ms:atMs+ttlMs,control_enabled:false};
}
export function navigationToMission(intent){
 if(intent?.schema!=='warirak.navigation-intent.v1'||intent.decision_interface!==NAV_ONLY_INTERFACE||intent.plant_environment!==MISSION_ENV_R2||intent.source!=='simulation'||intent.control_enabled!==false)throw Error('Unsupported navigation intent');
 const expected=navigationIntent(intent.action,intent.sequence,intent.issued_at_ms,intent.valid_until_ms-intent.issued_at_ms);
 if(intent.action_name!==expected.action_name)throw Error('Navigation action-name mismatch');
 return missionRequestR2(intent.sequence,intent.issued_at_ms,expected.action_name,intent.valid_until_ms-intent.issued_at_ms);
}
export function simulatedOperatorRecovery(sequence,atMs,ttlMs=400){
 // Separate explicit operator path; it is an API distinction, not an authentication mechanism.
 navigationIntent(0,sequence,atMs,ttlMs);
 return missionRequestR2(sequence,atMs,'RECOVERY_REQUEST',ttlMs);
}
