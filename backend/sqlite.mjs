import{DatabaseSync}from'node:sqlite';
export class SQLiteDatabase{
 constructor(path=':memory:'){this.sqlite=new DatabaseSync(path);this.sqlite.exec('PRAGMA foreign_keys=ON; PRAGMA journal_mode=WAL;');}
 prepare(sql){const db=this.sqlite;return{bind(...args){return statement(db,sql,args);},...statement(db,sql,[])};}
 async batch(statements){this.sqlite.exec('BEGIN IMMEDIATE');try{const results=statements.map(s=>s.execute());this.sqlite.exec('COMMIT');return results;}catch(error){this.sqlite.exec('ROLLBACK');throw error;}}
 close(){this.sqlite.close();}
}
function statement(db,sql,args){args=args.map(v=>v instanceof ArrayBuffer?new Uint8Array(v):v);const execute=()=>{const prepared=db.prepare(sql);if(/^\s*(SELECT|WITH)\b/i.test(sql))return{results:prepared.all(...args),meta:{changes:0}};const r=prepared.run(...args);return{success:true,meta:{changes:Number(r.changes)}};};return{execute,bind(...next){return statement(db,sql,next);},async first(){return db.prepare(sql).get(...args)||null;},async all(){return{results:db.prepare(sql).all(...args)};},async run(){return execute();}};}
