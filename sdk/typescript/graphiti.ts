import { Client, ClientOptions } from "./client";

export interface EntityNode { uuid:string;name:string;summary:string;group_id:string;labels:string[];attributes:Record<string,unknown>;created_at:string; }
export interface EntityEdge { uuid:string;fact:string;name:string;source_node_uuid:string;target_node_uuid:string;group_id:string;created_at:string; }
export interface EpisodicNode { uuid:string;episode_body:string;summary:string;group_id:string;created_at:string; }
export interface CommunityNode { uuid:string;name:string;summary:string;group_id:string;labels:string[];created_at:string; }
export interface SagaNode { uuid:string;name:string;summary:string;group_id:string;created_at:string; }
export interface SearchResults { nodes:EntityNode[];edges:EntityEdge[];episodes:EpisodicNode[]; }
export interface AddEpisodeResults { episode:EpisodicNode;nodes:EntityNode[];edges:EntityEdge[]; }
export interface GraphitiConfig { host?:string;port?:number|string;db?:string;token?:string;client?:Client; }

function _uuid():string{return"xxxxxxxx-xxxx-4xxx-yxxx-xxxxxxxxxxxx".replace(/[xy]/g,c=>{const r=Math.random()*16|0;return(c==='x'?r:(r&0x3)|0x8).toString(16);})}

function _r2en(r:any):EntityNode{
  let a:Record<string,unknown>={};
  try{a=r.metadata_json?JSON.parse(typeof r.metadata_json==='string'?r.metadata_json:JSON.stringify(r.metadata_json)):{}}catch{}
  return{uuid:r.id||"",name:r.label||"",summary:r.summary||"",group_id:r.workspace_id||"",
    labels:r.labels?(typeof r.labels==='string'?JSON.parse(r.labels):r.labels):[],attributes:a,
    created_at:r.created_at?new Date(Number(r.created_at)*1000).toISOString():new Date().toISOString()};
}
function _r2ee(r:any):EntityEdge{
  return{uuid:r.id||"",fact:r.label||r.relation||"",name:r.relation||r.label||"",
    source_node_uuid:r.source_node_id||"",target_node_uuid:r.target_node_id||"",group_id:r.workspace_id||"",
    created_at:r.created_at?new Date(Number(r.created_at)*1000).toISOString():new Date().toISOString()};
}
function _r2epn(r:any):EpisodicNode{
  return{uuid:r.id||"",episode_body:r.content||r.summary||"",summary:r.summary||"",
    group_id:r.workspace_id||"",created_at:r.created_at?new Date(Number(r.created_at)*1000).toISOString():new Date().toISOString()};
}
function _r2cn(r:any):CommunityNode{
  return{uuid:r.id||"",name:r.label||"",summary:r.summary||"",group_id:r.workspace_id||"",
    labels:r.labels?(typeof r.labels==='string'?JSON.parse(r.labels):r.labels):[],
    created_at:r.created_at?new Date(Number(r.created_at)*1000).toISOString():new Date().toISOString()};
}

export class EntityNodeNamespace{
  constructor(private _g:Graphiti){}
  async save(n:EntityNode):Promise<EntityNode>{
    const ws=await this._g._rws(n.group_id);
    await this._g._client.createNode(ws,n.name||n.summary,"entity",n.summary||n.name);
    return{...n,uuid:_uuid()};
  }
  async delete(_n:EntityNode):Promise<void>{}
  async getByUuid(u:string):Promise<EntityNode|null>{
    const rows=await this._g._client._call("sql",["SELECT * FROM kg_node WHERE id='"+u+"'"]);
    return rows?.length?_r2en(rows[0]):null;
  }
  async getByUuids(uuids:string[]):Promise<EntityNode[]>{
    if(!uuids.length)return[];
    const ids=uuids.map(u=>"'"+u+"'").join(",");
    const rows=await this._g._client._call("sql",["SELECT * FROM kg_node WHERE id IN ("+ids+")"]);
    return(rows||[]).map(_r2en);
  }
  async getByGroupIds(gids:string[],limit=100):Promise<EntityNode[]>{
    const a:EntityNode[]=[];
    for(const gid of gids){
      const ws=await this._g._rws(gid);
      const rows=await this._g._client._call("sql",["SELECT * FROM kg_node WHERE workspace_id='"+ws+"' AND node_type='entity' LIMIT "+limit]);
      a.push(...(rows||[]).map(_r2en));
    }
    return a;
  }
}

export class EpisodicNodeNamespace{
  constructor(private _g:Graphiti){}
  async save(n:EpisodicNode):Promise<EpisodicNode>{
    const ws=await this._g._rws(n.group_id);
    await this._g._client.store(ws,n.episode_body,{memoryType:"graphiti_episode"});
    return{...n,uuid:_uuid()};
  }
  async delete(_n:EpisodicNode):Promise<void>{}
  async getByUuid(u:string):Promise<EpisodicNode|null>{
    const rows=await this._g._client._call("sql",["SELECT * FROM memory WHERE id='"+u+"'"]);
    return rows?.length?_r2epn(rows[0]):null;
  }
  async getByUuids(uuids:string[]):Promise<EpisodicNode[]>{
    if(!uuids.length)return[];
    const ids=uuids.map(u=>"'"+u+"'").join(",");
    const rows=await this._g._client._call("sql",["SELECT * FROM memory WHERE id IN ("+ids+")"]);
    return(rows||[]).map(_r2epn);
  }
  async getByGroupIds(gids:string[],limit=100):Promise<EpisodicNode[]>{
    const a:EpisodicNode[]=[];
    for(const gid of gids){
      const ws=await this._g._rws(gid);
      const rows=await this._g._client._call("sql",["SELECT * FROM memory WHERE workspace_id='"+ws+"' AND memory_type='graphiti_episode' LIMIT "+limit]);
      a.push(...(rows||[]).map(_r2epn));
    }
    return a;
  }
}

export class CommunityNodeNamespace{
  constructor(private _g:Graphiti){}
  async getByUuid(u:string):Promise<CommunityNode|null>{
    const rows=await this._g._client._call("sql",["SELECT * FROM kg_node WHERE id='"+u+"' AND node_type='community'"]);
    return rows?.length?_r2cn(rows[0]):null;
  }
  async getByUuids(uuids:string[]):Promise<CommunityNode[]>{
    if(!uuids.length)return[];
    const ids=uuids.map(u=>"'"+u+"'").join(",");
    const rows=await this._g._client._call("sql",["SELECT * FROM kg_node WHERE id IN ("+ids+") AND node_type='community'"]);
    return(rows||[]).map(_r2cn);
  }
  async getByGroupIds(gids:string[],limit=100):Promise<CommunityNode[]>{
    const a:CommunityNode[]=[];
    for(const gid of gids){
      const ws=await this._g._rws(gid);
      const rows=await this._g._client._call("sql",["SELECT * FROM kg_node WHERE workspace_id='"+ws+"' AND node_type='community' LIMIT "+limit]);
      a.push(...(rows||[]).map(_r2cn));
    }
    return a;
  }
}

export class SagaNodeNamespace{
  constructor(private _g:Graphiti){}
  async save(n:SagaNode):Promise<SagaNode>{
    const ws=await this._g._rws(n.group_id);
    await this._g._client.createNode(ws,n.name,"saga",n.summary);
    return{...n,uuid:_uuid()};
  }
  async delete(_n:SagaNode):Promise<void>{}
  async getByUuid(_u:string):Promise<SagaNode|null>{return null;}
  async getByUuids(_u:string[]):Promise<SagaNode[]>{return[];}
  async getByGroupIds(_g:string[],_l=100):Promise<SagaNode[]>{return[];}
}

export class NodeNamespace{
  entity:EntityNodeNamespace;episodic:EpisodicNodeNamespace;community:CommunityNodeNamespace;saga:SagaNodeNamespace;
  constructor(g:Graphiti){this.entity=new EntityNodeNamespace(g);this.episodic=new EpisodicNodeNamespace(g);this.community=new CommunityNodeNamespace(g);this.saga=new SagaNodeNamespace(g);}
}

export class EntityEdgeNamespace{
  constructor(private _g:Graphiti){}
  async save(e:EntityEdge):Promise<EntityEdge>{
    const ws=await this._g._rws(e.group_id);
    await this._g._client.createEdge(ws,e.source_node_uuid,e.target_node_uuid,e.name,1.0);
    return{...e,uuid:_uuid()};
  }
  async delete(_e:EntityEdge):Promise<void>{}
  async getByUuid(u:string):Promise<EntityEdge|null>{
    const rows=await this._g._client._call("sql",["SELECT * FROM kg_edge WHERE id='"+u+"'"]);
    return rows?.length?_r2ee(rows[0]):null;
  }
  async getByUuids(uuids:string[]):Promise<EntityEdge[]>{
    if(!uuids.length)return[];
    const ids=uuids.map(u=>"'"+u+"'").join(",");
    const rows=await this._g._client._call("sql",["SELECT * FROM kg_edge WHERE id IN ("+ids+")"]);
    return(rows||[]).map(_r2ee);
  }
  async getByGroupIds(gids:string[],limit=100):Promise<EntityEdge[]>{
    const a:EntityEdge[]=[];
    for(const gid of gids){
      const ws=await this._g._rws(gid);
      const rows=await this._g._client._call("sql",["SELECT * FROM kg_edge WHERE workspace_id='"+ws+"' LIMIT "+limit]);
      a.push(...(rows||[]).map(_r2ee));
    }
    return a;
  }
  async getBetweenNodes(su:string,tu:string):Promise<EntityEdge[]>{
    const rows=await this._g._client._call("sql",["SELECT * FROM kg_edge WHERE source_node_id='"+su+"' AND target_node_id='"+tu+"'"]);
    return(rows||[]).map(_r2ee);
  }
  async getByNodeUuid(nu:string):Promise<EntityEdge[]>{
    const rows=await this._g._client._call("sql",["SELECT * FROM kg_edge WHERE source_node_id='"+nu+"' OR target_node_id='"+nu+"'"]);
    return(rows||[]).map(_r2ee);
  }
}

export class EpisodicEdgeNamespace{constructor(private _g:Graphiti){}async save(e:any):Promise<any>{return e;}async delete(_e:any):Promise<void>{}async getByUuid(_u:string):Promise<any>{return null;}async getByUuids(_u:string[]):Promise<any[]>{return[];}async getByGroupIds(_g:string[],_l=100):Promise<any[]>{return[];}}
export class CommunityEdgeNamespace{constructor(private _g:Graphiti){}async save(e:any):Promise<any>{return e;}async delete(_e:any):Promise<void>{}async getByUuid(_u:string):Promise<any>{return null;}async getByUuids(_u:string[]):Promise<any[]>{return[];}async getByGroupIds(_g:string[],_l=100):Promise<any[]>{return[];}}
export class HasEpisodeEdgeNamespace{constructor(private _g:Graphiti){}async save(e:any):Promise<any>{return e;}async delete(_e:any):Promise<void>{}async getByUuid(_u:string):Promise<any>{return null;}async getByUuids(_u:string[]):Promise<any[]>{return[];}async getByGroupIds(_g:string[],_l=100):Promise<any[]>{return[];}}
export class NextEpisodeEdgeNamespace{constructor(private _g:Graphiti){}async save(e:any):Promise<any>{return e;}async delete(_e:any):Promise<void>{}async getByUuid(_u:string):Promise<any>{return null;}async getByUuids(_u:string[]):Promise<any[]>{return[];}async getByGroupIds(_g:string[],_l=100):Promise<any[]>{return[];}}

export class EdgeNamespace{
  entity:EntityEdgeNamespace;episodic:EpisodicEdgeNamespace;community:CommunityEdgeNamespace;hasEpisode:HasEpisodeEdgeNamespace;nextEpisode:NextEpisodeEdgeNamespace;
  constructor(g:Graphiti){this.entity=new EntityEdgeNamespace(g);this.episodic=new EpisodicEdgeNamespace(g);this.community=new CommunityEdgeNamespace(g);this.hasEpisode=new HasEpisodeEdgeNamespace(g);this.nextEpisode=new NextEpisodeEdgeNamespace(g);}
}

export class Graphiti{
  _client:Client;_wsCache:Map<string,string>=new Map();nodes:NodeNamespace;edges:EdgeNamespace;
  constructor(config:GraphitiConfig={}){
    if(config.client){this._client=config.client;}else{this._client=new Client({host:config.host,port:config.port,database:config.db,token:config.token} as ClientOptions);}
    this.nodes=new NodeNamespace(this);this.edges=new EdgeNamespace(this);
  }
  async _rws(gid:string):Promise<string>{const c=this._wsCache.get(gid);if(c)return c;const ws=gid.replace(/[^a-zA-Z0-9_-]/g,"_");this._wsCache.set(gid,ws);return ws;}
  close():void{}
  async addTriplet(src:EntityNode,edge:EntityEdge,tgt:EntityNode,groupId?:string):Promise<{nodes:EntityNode[];edges:EntityEdge[]}>{
    const gid=groupId||src.group_id||"default";
    const s=await this.nodes.entity.save({...src,group_id:gid});
    const t=await this.nodes.entity.save({...tgt,group_id:gid});
    const e=await this.edges.entity.save({...edge,group_id:gid,source_node_uuid:s.uuid,target_node_uuid:t.uuid});
    return{nodes:[s,t],edges:[e]};
  }
  async addEpisode(body:string,groupId:string="default"):Promise<AddEpisodeResults>{
    const ws=await this._rws(groupId);
    await this._client.store(ws,body,{memoryType:"graphiti_episode"});
    const ep:EpisodicNode={uuid:_uuid(),episode_body:body,summary:body.substring(0,200),group_id:groupId,created_at:new Date().toISOString()};
    return{episode:ep,nodes:[],edges:[]};
  }
  async search(query:string,groupIds?:string[],_cu?:string,limit=10):Promise<EntityEdge[]>{
    const gids=groupIds||["default"];const a:EntityEdge[]=[];
    for(const gid of gids){
      const ws=await this._rws(gid);
      try{const results=await this._client.search(ws,query,{limit,semantic:true});for(const r of results)a.push({uuid:r.id||"",fact:r.content||"",name:"related_to",source_node_uuid:"",target_node_uuid:"",group_id:gid,created_at:new Date().toISOString()});}catch{}
    }
    return a;
  }
  async search_(query:string,groupIds?:string[],_cu?:string,limit=10):Promise<SearchResults>{const edges=await this.search(query,groupIds,_cu,limit);return{nodes:[],edges,episodes:[]};}
  async getEntityEdgeSummary(entityUuid:string):Promise<EntityEdge[]>{return this.edges.entity.getByNodeUuid(entityUuid);}
  async buildCommunities(groupIds?:string[]):Promise<CommunityNode[]>{
    if(!groupIds?.length)return[];const ws=await this._rws(groupIds[0]);
    try{await this._client._call("detect_communities",[ws]);}catch{}
    return this.nodes.community.getByGroupIds(groupIds);
  }
  async removeEpisode(episodeUuid:string):Promise<void>{try{await this._client._call("deactivate_memory",[episodeUuid]);}catch{}}
}
