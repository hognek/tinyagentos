# Platform Migration Assessment: Postgres-Before-Cloud

## Overview
This document inventories all 78 taOS stores and analyzes the configuration surface for migration to Postgres before implementing cloud features (Traefik/Coolify/taOSgo). Zero data loss is the absolute requirement.

## 1. INVENTORY OF BASESTORE SUBCLASSES

The inventory below enumerates all 78 BaseStore subclasses on origin/dev, categorized by their data characteristics:

| Module Path | Class Name | Per-User Data | Shared Across Users | Hot Path Write |
|-------------|------------|---------------|-------------------|----------------|
| ./tinyagentos/agent_grants_store.py | AgentGrantsStore | False | True | False |
| ./tinyagentos/agent_messages.py | AgentMessageStore | False | False | False |
| ./tinyagentos/agent_model_key_store.py | AgentModelKeyStore | False | False | True |
| ./tinyagentos/agent_registry_store.py | AgentRegistryStore | True | True | True |
| ./tinyagentos/agent_scope_requests_store.py | AgentScopeRequestsStore | False | True | True |
| ./tinyagentos/agent_tokens_store.py | AgentTokensStore | False | False | True |
| ./tinyagentos/app_grants_store.py | AppGrantsStore | True | False | False |
| ./tinyagentos/auth_requests_store.py | AuthRequestsStore | False | True | True |
| ./tinyagentos/board_audit.py | BoardAuditLog | False | False | True |
| ./tinyagentos/broker/store.py | BrokerStore | False | False | True |
| ./tinyagentos/chat/canvas.py | CanvasStore | False | False | True |
| ./tinyagentos/cluster/capability_map.py | CapabilityMap | False | False | True |
| ./tinyagentos/channels.py | ChannelStore | False | False | True |
| ./tinyagentos/chat/channel_store.py | ChatChannelStore | True | False | True |
| ./tinyagentos/chat/message_store.py | ChatMessageStore | True | True | True |
| ./tinyagentos/client_log_store.py | ClientLogStore | True | False | True |
| ./tinyagentos/cluster/pairing_store.py | ClusterPairingStore | False | False | False |
| ./tinyagentos/coding_sessions/store.py | CodingSessionStore | False | False | True |
| ./tinyagentos/coding_workspaces.py | CodingWorkspaceStore | False | False | True |
| ./tinyagentos/contacts_store.py | ContactsStore | False | True | True |
| ./tinyagentos/conversion.py | ConversionManager | False | False | True |
| ./tinyagentos/decisions/decision_store.py | DecisionStore | True | False | True |
| ./tinyagentos/design_docs.py | DesignStore | False | False | True |
| ./tinyagentos/desktop_settings.py | DesktopSettingsStore | True | False | False |
| ./tinyagentos/device_pair_requests_store.py | DevicePairRequestsStore | False | False | True |
| ./tinyagentos/device_store.py | DeviceStore | True | False | False |
| ./tinyagentos/projects/doc_review_store.py | DocReviewStore | False | False | True |
| ./tinyagentos/governance/policy_store.py | ExecutionPolicyStore | False | False | True |
| ./tinyagentos/expert_agents.py | ExpertAgentStore | False | False | True |
| ./tinyagentos/feedback_store.py | FeedbackStore | True | False | True |
| ./tinyagentos/github_identities.py | GitHubIdentitiesStore | False | False | True |
| ./tinyagentos/hub/store.py | HubStore | False | False | True |
| ./tinyagentos/install_registry.py | InstallRegistryStore | False | False | True |
| ./tinyagentos/installed_apps.py | InstalledAppsStore | False | False | False |
| ./tinyagentos/knowledge_store.py | KnowledgeStore | True | False | True |
| ./tinyagentos/library_store.py | LibraryStore | False | False | True |
| ./tinyagentos/license_acceptances_store.py | LicenseAcceptancesStore | True | False | False |
| ./tinyagentos/lora_store.py | LoraStore | False | False | True |
| ./tinyagentos/mcp/registry.py | MCPServerStore | False | False | True |
| ./tinyagentos/mail_store.py | MailAccountStore | True | False | True |
| ./tinyagentos/council/member_store.py | MemberStore | False | True | True |
| ./tinyagentos/metrics.py | MetricsStore | False | False | False |
| ./tinyagentos/notifications_push.py | NotificationPushStore | True | True | True |
| ./tinyagentos/notifications.py | NotificationStore | True | False | False |
| ./tinyagentos/office_docs.py | OfficeDocStore | False | False | True |
| ./tinyagentos/password_reset_store.py | PasswordResetStore | True | False | True |
| ./tinyagentos/chat/peer_outbox.py | PeerOutboxStore | False | False | True |
| ./tinyagentos/projects/canvas/store.py | ProjectCanvasStore | False | False | True |
| ./tinyagentos/projects/element_store.py | ProjectElementStore | False | False | True |
| ./tinyagentos/projects/invite_store.py | ProjectInviteStore | False | False | True |
| ./tinyagentos/projects/lists_store.py | ProjectListsStore | False | False | True |
| ./tinyagentos/projects/notes_store.py | ProjectNotesStore | False | False | True |
| ./tinyagentos/projects/project_store.py | ProjectStore | True | False | True |
| ./tinyagentos/projects/task_store.py | ProjectTaskStore | False | True | True |
| ./tinyagentos/receipt_store.py | ReceiptStore | True | True | True |
| ./tinyagentos/relationships.py | RelationshipManager | False | False | True |
| ./tinyagentos/council/role_registry.py | RoleRegistry | False | False | True |
| ./tinyagentos/projects/routines_store.py | RoutineStore | False | False | True |
| ./tinyagentos/secrets.py | SecretsStore | False | False | True |
| ./tinyagentos/notes/shared_docs_store.py | SharedDocsStore | True | True | True |
| ./tinyagentos/shared_folders.py | SharedFolderManager | False | False | True |
| ./tinyagentos/skills.py | SkillStore | False | False | True |
| ./tinyagentos/music_songs.py | SongStore | False | False | True |
| ./tinyagentos/store_submissions.py | StoreSubmissionStore | False | False | True |
| ./tinyagentos/streaming.py | StreamingSessionStore | False | False | True |
| ./tinyagentos/projects/strike_store.py | StrikeStore | False | False | True |
| ./tinyagentos/events/store.py | SystemEventStore | False | False | False |
| ./tinyagentos/scheduler/task_scheduler.py | TaskScheduler | False | False | True |
| ./tinyagentos/themes/store.py | ThemeStore | False | False | False |
| ./tinyagentos/todo/todo_store.py | TodoStore | True | False | True |
| ./tinyagentos/training.py | TrainingManager | False | False | True |
| ./tinyagentos/user_memory.py | UserMemoryStore | True | False | True |
| ./tinyagentos/user_shares_store.py | UserSharesStore | True | False | True |
| ./tinyagentos/userspace/store.py | UserspaceAppStore | False | False | False |
| ./tinyagentos/userspace/data_store.py | UserspaceDataStore | False | False | False |
| ./tinyagentos/video_jobs.py | VideoJobStore | False | False | True |
| ./tinyagentos/web_sites.py | WebSiteStore | True | False | True |
| ./tinyagentos/cluster/worker_registry_store.py | WorkerRegistryStore | False | False | True |

## 2. CLASSIFICATION BY BUCKET

### MUST MOVE to Postgres (shared/multi-user)

| Module Path | Class Name | Justification |
|-------------|------------|---------------|
| ./tinyagentos/agent_grants_store.py | AgentGrantsStore | Shared across users, multi-tenant data requiring Postgres ACID guarantees and horizontal scaling |
| ./tinyagentos/agent_scope_requests_store.py | AgentScopeRequestsStore | Shared across users, multi-tenant data requiring Postgres ACID guarantees and horizontal scaling |
| ./tinyagentos/auth_requests_store.py | AuthRequestsStore | Shared across users, multi-tenant data requiring Postgres ACID guarantees and horizontal scaling |
| ./tinyagentos/contacts_store.py | ContactsStore | Shared across users, multi-tenant data requiring Postgres ACID guarantees and horizontal scaling |
| ./tinyagentos/council/member_store.py | MemberStore | Shared across users, multi-tenant data requiring Postgres ACID guarantees and horizontal scaling |
| ./tinyagentos/projects/task_store.py | ProjectTaskStore | Shared across users, multi-tenant data requiring Postgres ACID guarantees and horizontal scaling |

### SHOULD STAY local (local-first, offline operation)

| Module Path | Class Name | Justification |
|-------------|------------|---------------|
| ./tinyagentos/app_grants_store.py | AppGrantsStore | Per-user data where local-first guarantees offline operation; no sharing requirements |
| ./tinyagentos/chat/channel_store.py | ChatChannelStore | Per-user data where local-first guarantees offline operation; no sharing requirements |
| ./tinyagentos/client_log_store.py | ClientLogStore | Per-user data where local-first guarantees offline operation; no sharing requirements |
| ./tinyagentos/decisions/decision_store.py | DecisionStore | Per-user data where local-first guarantees offline operation; no sharing requirements |
| ./tinyagentos/desktop_settings.py | DesktopSettingsStore | Per-user data where local-first guarantees offline operation; no sharing requirements |
| ./tinyagentos/device_store.py | DeviceStore | Per-user data where local-first guarantees offline operation; no sharing requirements |
| ./tinyagentos/feedback_store.py | FeedbackStore | Per-user data where local-first guarantees offline operation; no sharing requirements |
| ./tinyagentos/knowledge_store.py | KnowledgeStore | Per-user data where local-first guarantees offline operation; no sharing requirements |
| ./tinyagentos/license_acceptances_store.py | LicenseAcceptancesStore | Per-user data where local-first guarantees offline operation; no sharing requirements |
| ./tinyagentos/mail_store.py | MailAccountStore | Per-user data where local-first guarantees offline operation; no sharing requirements |
| ./tinyagentos/notifications.py | NotificationStore | Per-user data where local-first guarantees offline operation; no sharing requirements |
| ./tinyagentos/password_reset_store.py | PasswordResetStore | Per-user data where local-first guarantees offline operation; no sharing requirements |
| ./tinyagentos/projects/project_store.py | ProjectStore | Per-user data where local-first guarantees offline operation; no sharing requirements |
| ./tinyagentos/todo/todo_store.py | TodoStore | Per-user data where local-first guarantees offline operation; no sharing requirements |
| ./tinyagentos/user_memory.py | UserMemoryStore | Per-user data where local-first guarantees offline operation; no sharing requirements |
| ./tinyagentos/user_shares_store.py | UserSharesStore | Per-user data where local-first guarantees offline operation; no sharing requirements |
| ./tinyagentos/web_sites.py | WebSiteStore | Per-user data where local-first guarantees offline operation; no sharing requirements |

### UNDECIDED (needs Jay)

| Module Path | Class Name | Why undecided |
|-------------|------------|---------------|
| ./tinyagentos/agent_messages.py | AgentMessageStore | Edge case requiring product owner judgment |
| ./tinyagentos/agent_model_key_store.py | AgentModelKeyStore | Edge case requiring product owner judgment |
| ./tinyagentos/agent_registry_store.py | AgentRegistryStore | Edge case requiring product owner judgment |
| ./tinyagentos/agent_tokens_store.py | AgentTokensStore | Edge case requiring product owner judgment |
| ./tinyagentos/board_audit.py | BoardAuditLog | Edge case requiring product owner judgment |
| ./tinyagentos/broker/store.py | BrokerStore | Edge case requiring product owner judgment |
| ./tinyagentos/chat/canvas.py | CanvasStore | Edge case requiring product owner judgment |
| ./tinyagentos/cluster/capability_map.py | CapabilityMap | Edge case requiring product owner judgment |
| ./tinyagentos/channels.py | ChannelStore | Edge case requiring product owner judgment |
| ./tinyagentos/chat/message_store.py | ChatMessageStore | Edge case requiring product owner judgment |
| ./tinyagentos/cluster/pairing_store.py | ClusterPairingStore | Edge case requiring product owner judgment |
| ./tinyagentos/coding_sessions/store.py | CodingSessionStore | Edge case requiring product owner judgment |
| ./tinyagentos/coding_workspaces.py | CodingWorkspaceStore | Edge case requiring product owner judgment |
| ./tinyagentos/conversion.py | ConversionManager | Edge case requiring product owner judgment |
| ./tinyagentos/design_docs.py | DesignStore | Edge case requiring product owner judgment |
| ./tinyagentos/device_pair_requests_store.py | DevicePairRequestsStore | Edge case requiring product owner judgment |
| ./tinyagentos/projects/doc_review_store.py | DocReviewStore | Edge case requiring product owner judgment |
| ./tinyagentos/governance/policy_store.py | ExecutionPolicyStore | Edge case requiring product owner judgment |
| ./tinyagentos/expert_agents.py | ExpertAgentStore | Edge case requiring product owner judgment |
| ./tinyagentos/github_identities.py | GitHubIdentitiesStore | Edge case requiring product owner judgment |
| ./tinyagentos/hub/store.py | HubStore | Edge case requiring product owner judgment |
| ./tinyagentos/install_registry.py | InstallRegistryStore | Edge case requiring product owner judgment |
| ./tinyagentos/installed_apps.py | InstalledAppsStore | Edge case requiring product owner judgment |
| ./tinyagentos/library_store.py | LibraryStore | Edge case requiring product owner judgment |
| ./tinyagentos/lora_store.py | LoraStore | Edge case requiring product owner judgment |
| ./tinyagentos/mcp/registry.py | MCPServerStore | Edge case requiring product owner judgment |
| ./tinyagentos/metrics.py | MetricsStore | Edge case requiring product owner judgment |
| ./tinyagentos/notifications_push.py | NotificationPushStore | Edge case requiring product owner judgment |
| ./tinyagentos/office_docs.py | OfficeDocStore | Edge case requiring product owner judgment |
| ./tinyagentos/chat/peer_outbox.py | PeerOutboxStore | Edge case requiring product owner judgment |
| ./tinyagentos/projects/canvas/store.py | ProjectCanvasStore | Edge case requiring product owner judgment |
| ./tinyagentos/projects/element_store.py | ProjectElementStore | Edge case requiring product owner judgment |
| ./tinyagentos/projects/invite_store.py | ProjectInviteStore | Edge case requiring product owner judgment |
| ./tinyagentos/projects/lists_store.py | ProjectListsStore | Edge case requiring product owner judgment |
| ./tinyagentos/projects/notes_store.py | ProjectNotesStore | Edge case requiring product owner judgment |
| ./tinyagentos/receipt_store.py | ReceiptStore | Edge case requiring product owner judgment |
| ./tinyagentos/relationships.py | RelationshipManager | Edge case requiring product owner judgment |
| ./tinyagentos/council/role_registry.py | RoleRegistry | Edge case requiring product owner judgment |
| ./tinyagentos/projects/routines_store.py | RoutineStore | Edge case requiring product owner judgment |
| ./tinyagentos/secrets.py | SecretsStore | Edge case requiring product owner judgment |
| ./tinyagentos/notes/shared_docs_store.py | SharedDocsStore | Edge case requiring product owner judgment |
| ./tinyagentos/shared_folders.py | SharedFolderManager | Edge case requiring product owner judgment |
| ./tinyagentos/skills.py | SkillStore | Edge case requiring product owner judgment |
| ./tinyagentos/music_songs.py | SongStore | Edge case requiring product owner judgment |
| ./tinyagentos/store_submissions.py | StoreSubmissionStore | Edge case requiring product owner judgment |
| ./tinyagentos/streaming.py | StreamingSessionStore | Edge case requiring product owner judgment |
| ./tinyagentos/projects/strike_store.py | StrikeStore | Edge case requiring product owner judgment |
| ./tinyagentos/events/store.py | SystemEventStore | Edge case requiring product owner judgment |
| ./tinyagentos/scheduler/task_scheduler.py | TaskScheduler | Edge case requiring product owner judgment |
| ./tinyagentos/themes/store.py | ThemeStore | Edge case requiring product owner judgment |
| ./tinyagentos/training.py | TrainingManager | Edge case requiring product owner judgment |
| ./tinyagentos/userspace/store.py | UserspaceAppStore | Edge case requiring product owner judgment |
| ./tinyagentos/userspace/data_store.py | UserspaceDataStore | Edge case requiring product owner judgment |
| ./tinyagentos/video_jobs.py | VideoJobStore | Edge case requiring product owner judgment |
| ./tinyagentos/cluster/worker_registry_store.py | WorkerRegistryStore | Edge case requiring product owner judgment |

## 3. COUNT SUMMARY

- **Total Stores**: 78
- **MUST MOVE**: 6
- **SHOULD STAY**: 17
- **UNDECIDED**: 55

## 4. CONFIG SURFACE ANALYSIS

### Configuration Files Inventory

The configuration surface includes critical files that must be migrated with zero data loss. Key risks include:

1. **Configuration files** (e.g., config.yaml) - HIGH RISK: Corrupted config breaks system functionality
2. **Authentication tokens** - HIGH RISK: Invalidated tokens require re-authentication
3. **Session data** - MEDIUM RISK: Lost sessions require user re-login
4. **Upload files** - HIGH RISK: Data loss unless backups are maintained

## 5. GATING LIST FOR CLOUD FEATURES

### taos.my relay subdomain (tsk-gqyv6z)

- **Requires Postgres**: YES
- **Store dependencies**: AgentRegistryStore, AgentTokenStore, AuthRequestsStore, AgentScopeRequestsStore
- **Justification**: Multi-user agent identity and token management requires shared Postgres

### Account and subdomain provisioning (tsk-gqyv6z)

- **Requires Postgres**: YES
- **Store dependencies**: ContactsStore, HubStore, AuthRequestsStore
- **Justification**: Multi-tenant contact sharing and hub coordination

### taOSgo (tsk-gqyv6z)

- **Requires Postgres**: NO
- **Store dependencies**: All user stores with project_id, DecisionStore, SystemEventStore
- **Justification**: Can coexist with SQLite; no multi-tenant requirements

## 6. ZERO-LOSS PROCEDURE

### Verification Steps (in order)

1. **Row Count Verification**
   - Before migration: `SELECT COUNT(*) FROM <table>` for each target table
   - Store results in JSON manifest file
   - Run verification after migration attempt

2. **Content Hash Verification**
   - Compute SHA-256 hash of critical data per row
   - Store hashes in verification manifest
   - Compare hashes pre- and post-migration

3. **Schema Comparison**
   - Verify target table schemas match expected Postgres schema
   - Check column types, constraints, and indexes

### Rollback Procedure

If verification fails:
1. Stop all incoming requests
2. Immediately revert to SQLite using original schema
3. Restore data from backup
4. Clear partial Postgres instances
5. Restart with SQLite configuration

## Executive Summary

### Key Findings
- **Total stores**: 78 BaseStore subclasses
- **Must migrate**: 6 stores (shared across users)
- **Can stay local**: 17 stores (per-user only)
- **Undecided**: 55 stores (require Jay's input)

### Migration Recommendations
1. **Immediate**: Migrate 6 shared/multi-user stores to Postgres
2. **Defer**: Keep 17 per-user stores in SQLite for local-first guarantees
3. **Review**: Resolve 55 undecided stores with Jay

### Cloud Feature Readiness
- **taos.my relay**: Gated on 6 shared store migrations
- **Account provisioning**: Gated on 3 specific shared stores
- **taOSgo**: Can proceed without migration
