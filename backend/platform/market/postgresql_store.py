from __future__ import annotations

import json
from contextlib import contextmanager
from datetime import datetime, timezone
from typing import Any, Iterator
from uuid import uuid4

from backend.platform.database.identity import PostgreSQLIdentityResolver
from backend.platform.database.postgresql import PostgreSQLConnectionPool

from .store import _list, _object, _required, _timestamp


class PostgreSQLMarketStore:
    """Licensed market evidence, observations, rules and transactional events."""

    def __init__(self, pool: PostgreSQLConnectionPool, *, owns_pool: bool = False) -> None:
        self.pool = pool
        self.owns_pool = owns_pool

    def close(self) -> None:
        if self.owns_pool:
            self.pool.close()

    def create_source(self, tenant_id: str, payload: dict[str, Any], created_by: str) -> dict[str, Any]:
        source_system_key = _required(payload.get("source_system_id"), "source_system_id", 160)
        with self._transaction() as connection:
            tenant_key = PostgreSQLIdentityResolver.tenant_id(connection, tenant_id)
            actor_key = PostgreSQLIdentityResolver.user_id(connection, created_by)
            with connection.cursor() as cursor:
                cursor.execute(
                    "SELECT source_system_id,source_category,license_metadata FROM platform_source_systems WHERE tenant_id=%s AND source_system_key=%s AND status='active'",
                    (tenant_key, source_system_key),
                )
                source = cursor.fetchone()
                if not source or str(_value(source, "source_category", 1)) != "market":
                    raise ValueError("licensed_market_source_system_required")
                metadata = _json_value(_value(source, "license_metadata", 2), {})
                license_type = str(payload.get("license_type") or metadata.get("license_type") or "").strip()
                if not license_type:
                    raise ValueError("market_license_type_required")
                method = str(payload.get("acquisition_method") or "licensed_feed").strip()
                if method not in {"api", "database", "file", "licensed_feed", "manual_review"}:
                    raise ValueError("invalid_market_acquisition_method")
                key = str(payload.get("market_source_id") or f"ms_{uuid4().hex}")
                cursor.execute(
                    """
                    INSERT INTO platform_market_sources(
                        tenant_id,market_source_key,source_system_id,source_url,publisher,
                        acquisition_method,license_type,reliability_score,status,created_by
                    ) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,'active',%s)
                    """,
                    (
                        tenant_key,key,_value(source,"source_system_id",0),str(payload.get("source_url") or "") or None,
                        _required(payload.get("publisher"),"publisher",300),method,license_type,
                        max(0,min(float(payload.get("reliability_score",0.8)),1)),actor_key,
                    ),
                )
        return self.get_source(tenant_id,key)

    def get_source(self, tenant_id: str, source_id: str) -> dict[str, Any]:
        with self.pool.connection() as connection:
            tenant_key=PostgreSQLIdentityResolver.tenant_id(connection,tenant_id)
            with connection.cursor() as cursor:
                cursor.execute(self._source_select()+" WHERE s.tenant_id=%s AND s.market_source_key=%s",(tenant_key,source_id)); row=cursor.fetchone()
        if not row: raise KeyError("market_source_not_found")
        return _row(row)

    def create_entity(self, tenant_id: str, payload: dict[str, Any], created_by: str) -> dict[str, Any]:
        entity_type=str(payload.get("entity_type") or "institution").strip()
        if entity_type not in {"institution","product","industry","region","index","event_subject"}: raise ValueError("invalid_market_entity_type")
        key=str(payload.get("market_entity_id") or f"me_{uuid4().hex}")
        with self._transaction() as connection:
            tenant_key=PostgreSQLIdentityResolver.tenant_id(connection,tenant_id)
            actor_key=PostgreSQLIdentityResolver.user_id(connection,created_by)
            with connection.cursor() as cursor:
                cursor.execute("""INSERT INTO platform_market_entities(tenant_id,market_entity_key,entity_type,entity_code,entity_name,aliases,attributes,status,created_by)
                    VALUES (%s,%s,%s,%s,%s,%s::jsonb,%s::jsonb,'active',%s)""",
                    (tenant_key,key,entity_type,_required(payload.get("entity_code"),"entity_code",160),_required(payload.get("entity_name"),"entity_name",300),_json(_list(payload.get("aliases",[]))),_json(_object(payload.get("attributes",{}))),actor_key))
        return self.get_entity(tenant_id,key)

    def get_entity(self, tenant_id: str, entity_id: str) -> dict[str, Any]:
        with self.pool.connection() as connection:
            tenant_key=PostgreSQLIdentityResolver.tenant_id(connection,tenant_id)
            with connection.cursor() as cursor:
                cursor.execute(self._entity_select()+" WHERE e.tenant_id=%s AND e.market_entity_key=%s",(tenant_key,entity_id)); row=cursor.fetchone()
        if not row: raise KeyError("market_entity_not_found")
        return _row(row)

    def create_observation(self, tenant_id: str, payload: dict[str, Any], created_by: str) -> dict[str, Any]:
        source_id=_required(payload.get("market_source_id"),"market_source_id",160)
        entity_id=_required(payload.get("market_entity_id"),"market_entity_id",160)
        source=self.get_source(tenant_id,source_id)
        self.get_entity(tenant_id,entity_id)
        if source["status"]!="active": raise ValueError("market_source_is_not_active")
        artifact_id=_required(payload.get("evidence_artifact_id"),"evidence_artifact_id",160)
        numeric=payload.get("value_numeric"); text=str(payload.get("value_text") or "").strip() or None
        if numeric is None and text is None: raise ValueError("market_observation_value_required")
        source_record=_required(payload.get("source_record_id"),"source_record_id",300)
        metric=_required(payload.get("metric_code"),"metric_code",160)
        key=str(payload.get("market_observation_id") or f"mo_{uuid4().hex}")
        with self._transaction() as connection:
            tenant_key=PostgreSQLIdentityResolver.tenant_id(connection,tenant_id)
            actor_key=PostgreSQLIdentityResolver.user_id(connection,created_by)
            source_key=_lookup(connection,"platform_market_sources","market_source_id","market_source_key",tenant_key,source_id,"market_source_not_found")
            entity_key=_lookup(connection,"platform_market_entities","market_entity_id","market_entity_key",tenant_key,entity_id,"market_entity_not_found")
            artifact_key=_lookup(connection,"platform_data_artifacts","artifact_id","artifact_key",tenant_key,artifact_id,"data_artifact_not_found")
            with connection.cursor() as cursor:
                cursor.execute("SELECT status FROM platform_data_artifacts WHERE artifact_id=%s",(artifact_key,)); artifact=cursor.fetchone()
                if not artifact or str(_value(artifact,"status",0))!="active": raise ValueError("active_market_evidence_artifact_required")
                cursor.execute("""INSERT INTO platform_market_observations(
                    tenant_id,market_observation_key,market_source_id,market_entity_id,metric_code,observed_at,
                    value_numeric,value_text,unit,currency,evidence_artifact_id,source_record_id,confidence,created_by)
                    VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
                    ON CONFLICT (tenant_id,market_source_id,source_record_id,metric_code) DO NOTHING""",
                    (tenant_key,key,source_key,entity_key,metric,_timestamp(payload.get("observed_at")),float(numeric) if numeric is not None else None,text,str(payload.get("unit") or "") or None,str(payload.get("currency") or "")[:3] or None,artifact_key,source_record,max(0,min(float(payload.get("confidence",source["reliability_score"])),1)),actor_key))
                cursor.execute("SELECT market_observation_key FROM platform_market_observations WHERE tenant_id=%s AND market_source_id=%s AND source_record_id=%s AND metric_code=%s",(tenant_key,source_key,source_record,metric)); key=str(_value(cursor.fetchone(),"market_observation_key",0))
        return self._observation(tenant_id,key)

    def create_rule(self, tenant_id: str, payload: dict[str, Any], created_by: str) -> dict[str, Any]:
        condition=_object(payload.get("condition_expression",{}))
        if str(condition.get("operator") or "") not in {"gt","gte","lt","lte","eq","change_pct_gt","change_pct_lt"}: raise ValueError("invalid_market_rule_operator")
        if "threshold" not in condition: raise ValueError("market_rule_threshold_required")
        severity=str(payload.get("severity") or "warning")
        if severity not in {"info","warning","error","critical"}: raise ValueError("invalid_market_rule_severity")
        key=str(payload.get("market_rule_id") or f"mrule_{uuid4().hex}")
        with self._transaction() as connection:
            tenant_key=PostgreSQLIdentityResolver.tenant_id(connection,tenant_id); actor_key=PostgreSQLIdentityResolver.user_id(connection,created_by)
            with connection.cursor() as cursor:
                cursor.execute("""INSERT INTO platform_market_monitoring_rules(
                    tenant_id,market_rule_key,rule_name,entity_selector,metric_code,condition_expression,
                    severity,cooldown_seconds,status,owner_user_id,created_by)
                    VALUES (%s,%s,%s,%s::jsonb,%s,%s::jsonb,%s,%s,'active',%s,%s)""",
                    (tenant_key,key,_required(payload.get("rule_name"),"rule_name",300),_json(_object(payload.get("entity_selector",{}))),_required(payload.get("metric_code"),"metric_code",160),_json(condition),severity,max(0,min(int(payload.get("cooldown_seconds",3600)),31536000)),actor_key,actor_key))
        return self.get_rule(tenant_id,key)

    def get_rule(self, tenant_id: str, rule_id: str) -> dict[str, Any]:
        with self.pool.connection() as connection:
            tenant_key=PostgreSQLIdentityResolver.tenant_id(connection,tenant_id)
            with connection.cursor() as cursor:
                cursor.execute(self._rule_select()+" WHERE r.tenant_id=%s AND r.market_rule_key=%s",(tenant_key,rule_id)); row=cursor.fetchone()
        if not row: raise KeyError("market_rule_not_found")
        return _row(row)

    def list_rules(self, tenant_id: str) -> list[dict[str, Any]]:
        with self.pool.connection() as connection:
            tenant_key=PostgreSQLIdentityResolver.tenant_id(connection,tenant_id)
            with connection.cursor() as cursor:
                cursor.execute(self._rule_select()+" WHERE r.tenant_id=%s ORDER BY r.created_at DESC",(tenant_key,)); rows=cursor.fetchall()
        return [_row(row) for row in rows]

    def latest_observations(self, tenant_id: str, metric_code: str, limit_per_entity: int = 2) -> list[dict[str, Any]]:
        rows=self._observations(tenant_id,metric_code=metric_code,limit=5000)
        counts:dict[str,int]={}; result=[]
        for item in rows:
            entity=str(item["market_entity_id"])
            if counts.get(entity,0)>=limit_per_entity: continue
            result.append(item); counts[entity]=counts.get(entity,0)+1
        return result

    def list_observations(self, tenant_id: str, limit: int = 1000) -> list[dict[str, Any]]:
        return self._observations(tenant_id,limit=max(1,min(int(limit),5000)))

    def create_event(self, tenant_id: str, rule: dict[str, Any], observation: dict[str, Any], evidence: dict[str, Any]) -> dict[str, Any] | None:
        key=f"mke_{uuid4().hex}"
        with self._transaction() as connection:
            tenant_key=PostgreSQLIdentityResolver.tenant_id(connection,tenant_id)
            rule_key=_lookup(connection,"platform_market_monitoring_rules","market_rule_id","market_rule_key",tenant_key,str(rule["market_rule_id"]),"market_rule_not_found")
            entity_key=_lookup(connection,"platform_market_entities","market_entity_id","market_entity_key",tenant_key,str(observation["market_entity_id"]),"market_entity_not_found")
            observation_key=_lookup(connection,"platform_market_observations","market_observation_id","market_observation_key",tenant_key,str(observation["market_observation_id"]),"market_observation_not_found")
            with connection.cursor() as cursor:
                # A rule is the serialization boundary for cooldown decisions.
                # Lock it before checking prior events so distinct observations
                # evaluated by concurrent workers cannot both pass the gap.
                cursor.execute(
                    "SELECT market_rule_id FROM platform_market_monitoring_rules WHERE market_rule_id=%s FOR UPDATE",
                    (rule_key,),
                )
                if not cursor.fetchone():
                    raise KeyError("market_rule_not_found")
                cursor.execute("SELECT market_event_key FROM platform_market_monitoring_events WHERE market_rule_id=%s AND observation_id=%s",(rule_key,observation_key))
                if cursor.fetchone(): return None
                cursor.execute("SELECT detected_at FROM platform_market_monitoring_events WHERE tenant_id=%s AND market_rule_id=%s AND market_entity_id=%s AND status IN ('open','acknowledged') ORDER BY detected_at DESC LIMIT 1 FOR UPDATE",(tenant_key,rule_key,entity_key)); latest=cursor.fetchone()
                now=datetime.now(timezone.utc)
                if latest:
                    last=_value(latest,"detected_at",0)
                    if isinstance(last,str): last=datetime.fromisoformat(last.replace("Z","+00:00"))
                    if isinstance(last,datetime) and last.tzinfo is None:
                        last=last.replace(tzinfo=timezone.utc)
                    elif isinstance(last,datetime):
                        last=last.astimezone(timezone.utc)
                    if (now-last).total_seconds()<int(rule["cooldown_seconds"]): return None
                summary=f"{observation['entity_name']} 的 {rule['metric_code']} 触发规则“{rule['rule_name']}”，当前值 {observation.get('value_numeric') if observation.get('value_numeric') is not None else observation.get('value_text')}。"
                actor_key=_value(_fetch(cursor,"SELECT created_by FROM platform_market_monitoring_rules WHERE market_rule_id=%s",(rule_key,)),"created_by",0)
                cursor.execute("""INSERT INTO platform_market_monitoring_events(
                    tenant_id,market_event_key,market_rule_id,market_entity_id,observation_id,severity,status,event_summary,evidence,detected_at,created_by)
                    VALUES (%s,%s,%s,%s,%s,%s,'open',%s,%s::jsonb,%s,%s) RETURNING market_event_id""",
                    (tenant_key,key,rule_key,entity_key,observation_key,rule["severity"],summary,_json(evidence),now,actor_key))
                cursor.execute("""INSERT INTO platform_outbox_events(tenant_id,outbox_event_key,aggregate_type,aggregate_id,event_type,payload,status,created_by)
                    VALUES (%s,%s,'market_event',%s,'market.monitoring.triggered',%s::jsonb,'pending',%s)""",
                    (tenant_key,f"oe_{uuid4().hex}",key,_json({"market_event_id":key,"severity":rule["severity"],"summary":summary}),actor_key))
        return self.get_event(tenant_id,key)

    def get_event(self, tenant_id: str, event_id: str) -> dict[str, Any]:
        with self.pool.connection() as connection:
            tenant_key=PostgreSQLIdentityResolver.tenant_id(connection,tenant_id)
            with connection.cursor() as cursor:
                cursor.execute(self._event_select()+" WHERE e.tenant_id=%s AND e.market_event_key=%s",(tenant_key,event_id)); row=cursor.fetchone()
        if not row: raise KeyError("market_event_not_found")
        return _row(row)

    def list_events(self, tenant_id: str, limit: int = 200) -> list[dict[str, Any]]:
        with self.pool.connection() as connection:
            tenant_key=PostgreSQLIdentityResolver.tenant_id(connection,tenant_id)
            with connection.cursor() as cursor:
                cursor.execute(self._event_select()+" WHERE e.tenant_id=%s ORDER BY e.detected_at DESC LIMIT %s",(tenant_key,max(1,min(int(limit),500)))); rows=cursor.fetchall()
        return [_row(row) for row in rows]

    def update_event_status(self, tenant_id: str, event_id: str, status: str, actor_user_id: str) -> dict[str, Any]:
        if status not in {"acknowledged","resolved","suppressed"}: raise ValueError("invalid_market_event_status")
        with self._transaction() as connection:
            tenant_key=PostgreSQLIdentityResolver.tenant_id(connection,tenant_id); actor_key=PostgreSQLIdentityResolver.user_id(connection,actor_user_id)
            with connection.cursor() as cursor:
                cursor.execute("UPDATE platform_market_monitoring_events SET status=%s,acknowledged_by=%s,resolved_at=CASE WHEN %s='resolved' THEN now() ELSE resolved_at END,updated_at=now(),lock_version=lock_version+1 WHERE tenant_id=%s AND market_event_key=%s",(status,actor_key,status,tenant_key,event_id))
                if cursor.rowcount!=1: raise KeyError("market_event_not_found")
        return self.get_event(tenant_id,event_id)

    def bundle(self, tenant_id: str) -> dict[str, Any]:
        with self.pool.connection() as connection:
            tenant_key=PostgreSQLIdentityResolver.tenant_id(connection,tenant_id)
            with connection.cursor() as cursor:
                cursor.execute(self._source_select()+" WHERE s.tenant_id=%s ORDER BY s.created_at DESC",(tenant_key,)); sources=[_row(row) for row in cursor.fetchall()]
                cursor.execute(self._entity_select()+" WHERE e.tenant_id=%s ORDER BY e.created_at DESC",(tenant_key,)); entities=[_row(row) for row in cursor.fetchall()]
        return {"sources":sources,"entities":entities,"observations":self.list_observations(tenant_id),"rules":self.list_rules(tenant_id),"events":self.list_events(tenant_id)}

    def _observation(self,tenant_id:str,key:str)->dict[str,Any]:
        items=self._observations(tenant_id,observation_key=key,limit=1)
        if not items: raise KeyError("market_observation_not_found")
        return items[0]

    def _observations(self,tenant_id:str,*,metric_code:str|None=None,observation_key:str|None=None,limit:int)->list[dict[str,Any]]:
        with self.pool.connection() as connection:
            tenant_key=PostgreSQLIdentityResolver.tenant_id(connection,tenant_id)
            clauses=["o.tenant_id=%s"]; params:list[Any]=[tenant_key]
            if metric_code is not None: clauses.append("o.metric_code=%s");params.append(metric_code)
            if observation_key is not None: clauses.append("o.market_observation_key=%s");params.append(observation_key)
            params.append(limit)
            with connection.cursor() as cursor:
                cursor.execute(self._observation_select()+" WHERE "+" AND ".join(clauses)+" ORDER BY o.market_entity_id,o.observed_at DESC,o.created_at DESC LIMIT %s",tuple(params)); rows=cursor.fetchall()
        return [_row(row) for row in rows]

    @staticmethod
    def _source_select()->str:
        return """SELECT s.market_source_key AS market_source_id,tenant.tenant_code AS tenant_id,ss.source_system_key AS source_system_id,
            s.source_url,s.publisher,s.acquisition_method,s.license_type,s.reliability_score,s.status,
            creator.external_subject AS created_by,s.created_at,s.updated_at FROM platform_market_sources s
            JOIN platform_tenants tenant ON tenant.tenant_id=s.tenant_id JOIN platform_source_systems ss ON ss.source_system_id=s.source_system_id
            LEFT JOIN platform_user_profiles creator ON creator.user_id=s.created_by"""

    @staticmethod
    def _entity_select()->str:
        return """SELECT e.market_entity_key AS market_entity_id,tenant.tenant_code AS tenant_id,e.entity_type,e.entity_code,e.entity_name,
            e.aliases,e.attributes,e.status,creator.external_subject AS created_by,e.created_at,e.updated_at
            FROM platform_market_entities e JOIN platform_tenants tenant ON tenant.tenant_id=e.tenant_id
            LEFT JOIN platform_user_profiles creator ON creator.user_id=e.created_by"""

    @staticmethod
    def _observation_select()->str:
        return """SELECT o.market_observation_key AS market_observation_id,tenant.tenant_code AS tenant_id,
            s.market_source_key AS market_source_id,e.market_entity_key AS market_entity_id,o.metric_code,o.observed_at,
            o.value_numeric,o.value_text,o.unit,o.currency,a.artifact_key AS evidence_artifact_id,o.source_record_id,
            o.confidence,creator.external_subject AS created_by,o.created_at,e.entity_type,e.entity_name,e.attributes,
            s.publisher,s.license_type,s.source_url,a.content_hash AS evidence_hash
            FROM platform_market_observations o JOIN platform_tenants tenant ON tenant.tenant_id=o.tenant_id
            JOIN platform_market_entities e ON e.market_entity_id=o.market_entity_id
            JOIN platform_market_sources s ON s.market_source_id=o.market_source_id
            JOIN platform_data_artifacts a ON a.artifact_id=o.evidence_artifact_id
            LEFT JOIN platform_user_profiles creator ON creator.user_id=o.created_by"""

    @staticmethod
    def _rule_select()->str:
        return """SELECT r.market_rule_key AS market_rule_id,tenant.tenant_code AS tenant_id,r.rule_name,r.entity_selector,
            r.metric_code,r.condition_expression,r.severity,r.cooldown_seconds,r.status,
            owner.external_subject AS owner_user_id,creator.external_subject AS created_by,r.created_at,r.updated_at
            FROM platform_market_monitoring_rules r JOIN platform_tenants tenant ON tenant.tenant_id=r.tenant_id
            JOIN platform_user_profiles owner ON owner.user_id=r.owner_user_id LEFT JOIN platform_user_profiles creator ON creator.user_id=r.created_by"""

    @staticmethod
    def _event_select()->str:
        return """SELECT e.market_event_key AS market_event_id,tenant.tenant_code AS tenant_id,r.market_rule_key AS market_rule_id,
            entity.market_entity_key AS market_entity_id,o.market_observation_key AS observation_id,e.severity,e.status,
            e.event_summary,e.evidence,e.detected_at,ack.external_subject AS acknowledged_by,e.resolved_at,
            creator.external_subject AS created_by,e.created_at,e.updated_at
            FROM platform_market_monitoring_events e JOIN platform_tenants tenant ON tenant.tenant_id=e.tenant_id
            JOIN platform_market_monitoring_rules r ON r.market_rule_id=e.market_rule_id
            JOIN platform_market_entities entity ON entity.market_entity_id=e.market_entity_id
            LEFT JOIN platform_market_observations o ON o.market_observation_id=e.observation_id
            LEFT JOIN platform_user_profiles ack ON ack.user_id=e.acknowledged_by
            LEFT JOIN platform_user_profiles creator ON creator.user_id=e.created_by"""

    @contextmanager
    def _transaction(self)->Iterator[Any]:
        with self.pool.connection() as connection:
            try: yield connection;connection.commit()
            except BaseException: connection.rollback();raise


def _lookup(connection:Any,table:str,id_field:str,key_field:str,tenant_key:Any,key:str,error:str)->Any:
    allowed={("platform_market_sources","market_source_id","market_source_key"),("platform_market_entities","market_entity_id","market_entity_key"),("platform_market_observations","market_observation_id","market_observation_key"),("platform_market_monitoring_rules","market_rule_id","market_rule_key"),("platform_data_artifacts","artifact_id","artifact_key")}
    if (table,id_field,key_field) not in allowed: raise ValueError("unsafe_market_lookup")
    with connection.cursor() as cursor: cursor.execute(f"SELECT {id_field} FROM {table} WHERE tenant_id=%s AND {key_field}=%s",(tenant_key,key));row=cursor.fetchone()
    if not row: raise KeyError(error)
    return _value(row,id_field,0)


def _fetch(cursor:Any,sql:str,params:tuple[Any,...])->Any:
    cursor.execute(sql,params);row=cursor.fetchone()
    if not row: raise KeyError("market_resource_not_found")
    return row


def _row(row:Any)->dict[str,Any]:
    if not isinstance(row,dict): return {}
    return {str(key):_convert(value) for key,value in row.items()}


def _convert(value:Any)->Any:
    if isinstance(value,datetime): return value.isoformat()
    if hasattr(value,"as_tuple"): return float(value)
    return value


def _json_value(value:Any,default:Any)->Any:
    if value is None:return default
    if isinstance(value,(dict,list)):return value
    try:return json.loads(value)
    except (TypeError,json.JSONDecodeError):return default


def _value(row:Any,key:str,index:int)->Any:
    if isinstance(row,dict):return row[key]
    try:return row[key]
    except (TypeError,KeyError,IndexError):return row[index]


def _json(value:Any)->str:
    return json.dumps(value,ensure_ascii=False,sort_keys=True,default=str,separators=(",",":"))
