"""Facade that centralizes policy decision shaping."""
from src.console.policy.dedicated import DedicatedPolicy
from src.console.policy.gateway import GatewayPolicy
from src.console.policy.quota import QuotaPolicy
from src.console.policy.rbac import RbacPolicy


class PolicyService:
    def __init__(self, get_permissions=None, post_permissions=None, websocket_permissions=None):
        self.rbac = RbacPolicy(get_permissions=get_permissions, post_permissions=post_permissions, websocket_permissions=websocket_permissions)
        self.quota = QuotaPolicy()
        self.dedicated = DedicatedPolicy()
        self.gateway = GatewayPolicy()

    def permission_for(self, method, path):
        return self.rbac.permission_for(method, path)

    def authorize(self, identity, permission, action=""):
        return self.rbac.authorize(identity, permission, action)

    def request_decision(self, method, path, identity):
        return self.rbac.request_decision(method, path, identity)

    def quota_decision(self, result):
        return self.quota.from_quota_result(result)

    def dedicated_build_budget_decision(self, budget_state, cfg=None):
        return self.dedicated.build_budget(budget_state, cfg=cfg)

    def dedicated_lifecycle_decision(self, cfg, idle_policy, unhealthy_policy):
        return self.dedicated.lifecycle(cfg, idle_policy, unhealthy_policy)

    def dedicated_keep_alive_decision(self, cfg, seconds, allowed_seconds):
        return self.dedicated.keep_alive(cfg, seconds, allowed_seconds)

    def gateway_decision(self, metadata):
        return self.gateway.from_metadata(metadata)
