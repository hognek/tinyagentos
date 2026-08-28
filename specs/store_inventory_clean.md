# Platform Migration Assessment: Postgres-Before-Cloud

## Overview
This document inventories all 79 taOS stores and analyzes the configuration surface for migration to Postgres before implementing cloud features (Traefik/Coolify/taOSgo). Zero data loss is the absolute requirement.

## 1. INVENTORY OF BASESTORE SUBCLASSES

The inventory below enumerates all 79 BaseStore subclasses on origin/dev, categorized by their data characteristics:

| Module Path | Class Name | Per-User Data | Shared Across Users | Hot Path Write |
| ./tinyagentos/agent_grants_store.py | AgentGrantsStore | True | True | True |
| ./tinyagentos/agent_messages.py | AgentMessageStore | True | False | True |
| ./tinyagentos/agent_model_key_store.py | AgentModelKeyStore | False | True | True |
| ./tinyagentos/agent_registry_store.py | AgentRegistryStore | True | True | True |
| ./tinyagentos/agent_scope_requests_store.py | AgentScopeRequestsStore | True | True | False |
| ./tinyagentos/agent_tokens_store.py | AgentTokensStore | True | False | True |
| ./tinyagentos/app_grants_store.py | AppGrantsStore | True | True | False |
| ./tinyagentos/auth_requests_store.py | AuthRequestsStore | True | True | False |
| ./tinyagentos/board_audit.py | BoardAuditLog | True | False | True |
| ./tinyagentos/broker/store.py | BrokerStore | False | False | True |
| ./tinyagentos/channels.py | ChannelStore | True | False | True |
| ./tinyagentos/chat/canvas.py | CanvasStore | False | True | True |
| ./tinyagentos/chat/channel_store.py | ChatChannelStore | True | False | True |
| ./tinyagentos/chat/message_store.py | ChatMessageStore | True | True | True |
| ./tinyagentos/chat/peer_outbox.py | PeerOutboxStore | False | False | True |
| ./tinyagentos/client_log_store.py | ClientLogStore | True | False | True |
| ./tinyagentos/cluster/capability_map.py | CapabilityMap | False | False | False |
| ./tinyagentos/cluster/pairing_store.py | ClusterPairingStore | False | False | False |
| ./tinyagentos/cluster/worker_registry_store.py | WorkerRegistryStore | False | False | False |
| ./tinyagentos/coding_sessions/store.py | CodingSessionStore | True | False | True |
| ./tinyagentos/coding_workspaces.py | CodingWorkspaceStore | False | False | True |
| ./tinyagentos/contacts_store.py | ContactsStore | False | True | True |
| ./tinyagentos/conversion.py | ConversionManager | False | False | True |
| ./tinyagentos/council/member_store.py | MemberStore | False | True | False |
| ./tinyagentos/council/role_registry.py | RoleRegistry | False | False | False |
| ./tinyagentos/decisions/decision_store.py | DecisionStore | True | False | True |
| ./tinyagentos/design_docs.py | DesignStore | False | False | True |
| ./tinyagentos/desktop_settings.py | DesktopSettingsStore | True | False | False |
| ./tinyagentos/device_pair_requests_store.py | DevicePairRequestsStore | False | False | True |
| ./tinyagentos/device_store.py | DeviceStore | True | False | False |
| ./tinyagentos/events/store.py | SystemEventStore | False | True | False |
| ./tinyagentos/expert_agents.py | ExpertAgentStore | False | True | True |
| ./tinyagentos/feedback_store.py | FeedbackStore | True | False | True |
| ./tinyagentos/github_identities.py | GitHubIdentitiesStore | False | False | True |
| ./tinyagentos/governance/policy_store.py | ExecutionPolicyStore | True | True | True |
| ./tinyagentos/hub/store.py | HubStore | False | False | True |
| ./tinyagentos/install_registry.py | InstallRegistryStore | False | False | True |
| ./tinyagentos/installed_apps.py | InstalledAppsStore | False | False | False |
| ./tinyagentos/knowledge_store.py | KnowledgeStore | True | False | True |
| ./tinyagentos/library_store.py | LibraryStore | False | False | True |
| ./tinyagentos/license_acceptances_store.py | LicenseAcceptancesStore | True | False | False |
| ./tinyagentos/lora_store.py | LoraStore | False | False | True |
| ./tinyagentos/mail_store.py | MailAccountStore | True | False | True |
| ./tinyagentos/mcp/registry.py | MCPServerStore | True | False | True |
| ./tinyagentos/metrics.py | MetricsStore | False | False | True |
| ./tinyagentos/music_songs.py | SongStore | False | False | True |
| ./tinyagentos/notes/shared_docs_store.py | SharedDocsStore | True | True | True |
| ./tinyagentos/notifications.py | NotificationStore | True | True | True |
| ./tinyagentos/notifications_push.py | NotificationPushStore | True | True | True |
| ./tinyagentos/office_docs.py | OfficeDocStore | False | False | True |
| ./tinyagentos/password_reset_store.py | PasswordResetStore | True | False | True |
| ./tinyagentos/projects/canvas/store.py | ProjectCanvasStore | True | False | True |
| ./tinyagentos/projects/doc_review_store.py | DocReviewStore | True | False | True |
| ./tinyagentos/projects/element_store.py | ProjectElementStore | True | True | True |
| ./tinyagentos/projects/invite_store.py | ProjectInviteStore | True | False | False |
| ./tinyagentos/projects/lists_store.py | ProjectListsStore | True | True | True |
| ./tinyagentos/projects/notes_store.py | ProjectNotesStore | True | False | True |
| ./tinyagentos/projects/project_store.py | ProjectStore | True | False | True |
| ./tinyagentos/projects/routines_store.py | RoutineStore | True | False | True |
| ./tinyagentos/projects/strike_store.py | StrikeStore | False | False | True |
| ./tinyagentos/projects/task_store.py | ProjectTaskStore | True | True | True |
| ./tinyagentos/receipt_store.py | ReceiptStore | True | True | True |
| ./tinyagentos/relationships.py | RelationshipManager | True | False | True |
| ./tinyagentos/scheduler/task_scheduler.py | TaskScheduler | True | False | True |
| ./tinyagentos/secrets.py | SecretsStore | True | False | True |
| ./tinyagentos/shared_folders.py | SharedFolderManager | True | True | True |
| ./tinyagentos/skills.py | SkillStore | True | True | True |
| ./tinyagentos/store_submissions.py | StoreSubmissionStore | False | False | True |
| ./tinyagentos/streaming.py | StreamingSessionStore | True | False | False |
| ./tinyagentos/themes/store.py | ThemeStore | False | False | False |
| ./tinyagentos/todo/todo_store.py | TodoStore | True | False | True |
| ./tinyagentos/training.py | TrainingManager | True | False | True |
| ./tinyagentos/user_memory.py | UserMemoryStore | True | False | True |
| ./tinyagentos/user_shares_store.py | UserSharesStore | True | True | True |
| ./tinyagentos/userspace/data_store.py | UserspaceDataStore | False | False | False |
| ./tinyagentos/userspace/store.py | UserspaceAppStore | False | False | False |
| ./tinyagentos/video_jobs.py | VideoJobStore | False | False | True |
| ./tinyagentos/web_sites.py | WebSiteStore | True | False | True |

### MUST MOVE to Postgres (shared/multi-user)

| Module Path | Class Name | Justification |
|-------------|------------|---------------|
| ./tinyagentos/agent_grants_store.py | AgentGrantsStore | Shared across users, multi-tenant data that requires Postgres ACID guarantees and horizontal scaling |
| ./tinyagentos/agent_model_key_store.py | AgentModelKeyStore | Shared across users, multi-tenant data that requires Postgres ACID guarantees and horizontal scaling |
| ./tinyagentos/agent_registry_store.py | AgentRegistryStore | Shared across users, multi-tenant data that requires Postgres ACID guarantees and horizontal scaling |
| ./tinyagentos/agent_scope_requests_store.py | AgentScopeRequestsStore | Shared across users, multi-tenant data that requires Postgres ACID guarantees and horizontal scaling |
| ./tinyagentos/app_grants_store.py | AppGrantsStore | Shared across users, multi-tenant data that requires Postgres ACID guarantees and horizontal scaling |
| ./tinyagentos/auth_requests_store.py | AuthRequestsStore | Shared across users, multi-tenant data that requires Postgres ACID guarantees and horizontal scaling |
| ./tinyagentos/chat/canvas.py | CanvasStore | Shared across users, multi-tenant data that requires Postgres ACID guarantees and horizontal scaling |
| ./tinyagentos/chat/message_store.py | ChatMessageStore | Shared across users, multi-tenant data that requires Postgres ACID guarantees and horizontal scaling |
| ./tinyagentos/contacts_store.py | ContactsStore | Shared across users, multi-tenant data that requires Postgres ACID guarantees and horizontal scaling |
| ./tinyagentos/council/member_store.py | MemberStore | Shared across users, multi-tenant data that requires Postgres ACID guarantees and horizontal scaling |
| ./tinyagentos/events/store.py | SystemEventStore | Shared across users, multi-tenant data that requires Postgres ACID guarantees and horizontal scaling |
| ./tinyagentos/expert_agents.py | ExpertAgentStore | Shared across users, multi-tenant data that requires Postgres ACID guarantees and horizontal scaling |
| ./tinyagentos/governance/policy_store.py | ExecutionPolicyStore | Shared across users, multi-tenant data that requires Postgres ACID guarantees and horizontal scaling |
| ./tinyagentos/notes/shared_docs_store.py | SharedDocsStore | Shared across users, multi-tenant data that requires Postgres ACID guarantees and horizontal scaling |
| ./tinyagentos/notifications.py | NotificationStore | Shared across users, multi-tenant data that requires Postgres ACID guarantees and horizontal scaling |
| ./tinyagentos/notifications_push.py | NotificationPushStore | Shared across users, multi-tenant data that requires Postgres ACID guarantees and horizontal scaling |
| ./tinyagentos/projects/element_store.py | ProjectElementStore | Shared across users, multi-tenant data that requires Postgres ACID guarantees and horizontal scaling |
| ./tinyagentos/projects/lists_store.py | ProjectListsStore | Shared across users, multi-tenant data that requires Postgres ACID guarantees and horizontal scaling |
| ./tinyagentos/projects/task_store.py | ProjectTaskStore | Shared across users, multi-tenant data that requires Postgres ACID guarantees and horizontal scaling |
| ./tinyagentos/receipt_store.py | ReceiptStore | Shared across users, multi-tenant data that requires Postgres ACID guarantees and horizontal scaling |
| ./tinyagentos/shared_folders.py | SharedFolderManager | Shared across users, multi-tenant data that requires Postgres ACID guarantees and horizontal scaling |
| ./tinyagentos/skills.py | SkillStore | Shared across users, multi-tenant data that requires Postgres ACID guarantees and horizontal scaling |
| ./tinyagentos/user_shares_store.py | UserSharesStore | Shared across users, multi-tenant data that requires Postgres ACID guarantees and horizontal scaling |

### SHOULD STAY local (local-first, offline operation)

| Module Path | Class Name | Justification |
|-------------|------------|---------------|
| ./tinyagentos/agent_messages.py | AgentMessageStore | Per-user data where local-first guarantees offline operation and low-latency access; no sharing requirements |
| ./tinyagentos/agent_tokens_store.py | AgentTokensStore | Per-user data where local-first guarantees offline operation and low-latency access; no sharing requirements |
| ./tinyagentos/board_audit.py | BoardAuditLog | Per-user data where local-first guarantees offline operation and low-latency access; no sharing requirements |
| ./tinyagentos/channels.py | ChannelStore | Per-user data where local-first guarantees offline operation and low-latency access; no sharing requirements |
| ./tinyagentos/chat/channel_store.py | ChatChannelStore | Per-user data where local-first guarantees offline operation and low-latency access; no sharing requirements |
| ./tinyagentos/client_log_store.py | ClientLogStore | Per-user data where local-first guarantees offline operation and low-latency access; no sharing requirements |
| ./tinyagentos/coding_sessions/store.py | CodingSessionStore | Per-user data where local-first guarantees offline operation and low-latency access; no sharing requirements |
| ./tinyagentos/decisions/decision_store.py | DecisionStore | Per-user data where local-first guarantees offline operation and low-latency access; no sharing requirements |
| ./tinyagentos/desktop_settings.py | DesktopSettingsStore | Per-user data where local-first guarantees offline operation and low-latency access; no sharing requirements |
| ./tinyagentos/device_store.py | DeviceStore | Per-user data where local-first guarantees offline operation and low-latency access; no sharing requirements |
| ./tinyagentos/feedback_store.py | FeedbackStore | Per-user data where local-first guarantees offline operation and low-latency access; no sharing requirements |
| ./tinyagentos/knowledge_store.py | KnowledgeStore | Per-user data where local-first guarantees offline operation and low-latency access; no sharing requirements |
| ./tinyagentos/license_acceptances_store.py | LicenseAcceptancesStore | Per-user data where local-first guarantees offline operation and low-latency access; no sharing requirements |
| ./tinyagentos/mail_store.py | MailAccountStore | Per-user data where local-first guarantees offline operation and low-latency access; no sharing requirements |
| ./tinyagentos/mcp/registry.py | MCPServerStore | Per-user data where local-first guarantees offline operation and low-latency access; no sharing requirements |
| ./tinyagentos/password_reset_store.py | PasswordResetStore | Per-user data where local-first guarantees offline operation and low-latency access; no sharing requirements |
| ./tinyagentos/projects/canvas/store.py | ProjectCanvasStore | Per-user data where local-first guarantees offline operation and low-latency access; no sharing requirements |
| ./tinyagentos/projects/doc_review_store.py | DocReviewStore | Per-user data where local-first guarantees offline operation and low-latency access; no sharing requirements |
| ./tinyagentos/projects/invite_store.py | ProjectInviteStore | Per-user data where local-first guarantees offline operation and low-latency access; no sharing requirements |
| ./tinyagentos/projects/notes_store.py | ProjectNotesStore | Per-user data where local-first guarantees offline operation and low-latency access; no sharing requirements |
| ./tinyagentos/projects/project_store.py | ProjectStore | Per-user data where local-first guarantees offline operation and low-latency access; no sharing requirements |
| ./tinyagentos/projects/routines_store.py | RoutineStore | Per-user data where local-first guarantees offline operation and low-latency access; no sharing requirements |
| ./tinyagentos/relationships.py | RelationshipManager | Per-user data where local-first guarantees offline operation and low-latency access; no sharing requirements |
| ./tinyagentos/scheduler/task_scheduler.py | TaskScheduler | Per-user data where local-first guarantees offline operation and low-latency access; no sharing requirements |
| ./tinyagentos/secrets.py | SecretsStore | Per-user data where local-first guarantees offline operation and low-latency access; no sharing requirements |
| ./tinyagentos/streaming.py | StreamingSessionStore | Per-user data where local-first guarantees offline operation and low-latency access; no sharing requirements |
| ./tinyagentos/todo/todo_store.py | TodoStore | Per-user data where local-first guarantees offline operation and low-latency access; no sharing requirements |
| ./tinyagentos/training.py | TrainingManager | Per-user data where local-first guarantees offline operation and low-latency access; no sharing requirements |
| ./tinyagentos/user_memory.py | UserMemoryStore | Per-user data where local-first guarantees offline operation and low-latency access; no sharing requirements |
| ./tinyagentos/web_sites.py | WebSiteStore | Per-user data where local-first guarantees offline operation and low-latency access; no sharing requirements |

### UNDECIDED (needs Jay)

| Module Path | Class Name | Why undecided |
|-------------|------------|---------------|
| ./tinyagentos/broker/store.py | BrokerStore | Neutral classification; requires product owner judgment on migration priority |
| ./tinyagentos/chat/peer_outbox.py | PeerOutboxStore | Neutral classification; requires product owner judgment on migration priority |
| ./tinyagentos/cluster/capability_map.py | CapabilityMap | Neutral classification; requires product owner judgment on migration priority |
| ./tinyagentos/cluster/pairing_store.py | ClusterPairingStore | Neutral classification; requires product owner judgment on migration priority |
| ./tinyagentos/cluster/worker_registry_store.py | WorkerRegistryStore | Neutral classification; requires product owner judgment on migration priority |
| ./tinyagentos/coding_workspaces.py | CodingWorkspaceStore | Neutral classification; requires product owner judgment on migration priority |
| ./tinyagentos/conversion.py | ConversionManager | Neutral classification; requires product owner judgment on migration priority |
| ./tinyagentos/council/role_registry.py | RoleRegistry | Neutral classification; requires product owner judgment on migration priority |
| ./tinyagentos/design_docs.py | DesignStore | Neutral classification; requires product owner judgment on migration priority |
| ./tinyagentos/device_pair_requests_store.py | DevicePairRequestsStore | Neutral classification; requires product owner judgment on migration priority |
| ./tinyagentos/github_identities.py | GitHubIdentitiesStore | Neutral classification; requires product owner judgment on migration priority |
| ./tinyagentos/hub/store.py | HubStore | Neutral classification; requires product owner judgment on migration priority |
| ./tinyagentos/install_registry.py | InstallRegistryStore | Neutral classification; requires product owner judgment on migration priority |
| ./tinyagentos/installed_apps.py | InstalledAppsStore | Neutral classification; requires product owner judgment on migration priority |
| ./tinyagentos/library_store.py | LibraryStore | Neutral classification; requires product owner judgment on migration priority |
| ./tinyagentos/lora_store.py | LoraStore | Neutral classification; requires product owner judgment on migration priority |
| ./tinyagentos/metrics.py | MetricsStore | Neutral classification; requires product owner judgment on migration priority |
| ./tinyagentos/music_songs.py | SongStore | Neutral classification; requires product owner judgment on migration priority |
| ./tinyagentos/office_docs.py | OfficeDocStore | Neutral classification; requires product owner judgment on migration priority |
| ./tinyagentos/projects/strike_store.py | StrikeStore | Neutral classification; requires product owner judgment on migration priority |
| ./tinyagentos/store_submissions.py | StoreSubmissionStore | Neutral classification; requires product owner judgment on migration priority |
| ./tinyagentos/themes/store.py | ThemeStore | Neutral classification; requires product owner judgment on migration priority |
| ./tinyagentos/userspace/data_store.py | UserspaceDataStore | Neutral classification; requires product owner judgment on migration priority |
| ./tinyagentos/userspace/store.py | UserspaceAppStore | Neutral classification; requires product owner judgment on migration priority |
| ./tinyagentos/video_jobs.py | VideoJobStore | Neutral classification; requires product owner judgment on migration priority |

## 3. COUNT SUMMARY

- **Total Stores**: 78
- **MUST MOVE**: 23
- **SHOULD STAY**: 30
- **UNDECIDED**: 25

## 4. CONFIG SURFACE ANALYSIS

Inventory of configuration files under /opt/taos/data and their migration risks:

### Existing Configuration Files

| Path (relative to data dir) | File Size | Failed Migration Cost | Recovery Method |
|-------------------------------|-----------|---------------------|-----------------|
| archive/2026/04/12.jsonl | 726 bytes | LOW - Non-critical data | Can be reconfigured or rebuilt |
| archive/2026/04/12.jsonl | 726 bytes | LOW - Non-critical data | Can be reconfigured or rebuilt |
| archive/2026/04/13.jsonl | 938 bytes | LOW - Non-critical data | Can be reconfigured or rebuilt |
| archive/2026/04/13.jsonl | 938 bytes | LOW - Non-critical data | Can be reconfigured or rebuilt |
| config.yaml.example | 1,072 bytes | HIGH - Configuration controls core behavior | Restart with defaults + manual configuration |
| config.yaml.example | 1,072 bytes | HIGH - Configuration controls core behavior | Restart with defaults + manual configuration |
| guides.yaml | 7,128 bytes | LOW - Non-critical data | Can be reconfigured or rebuilt |
| guides.yaml | 7,128 bytes | LOW - Non-critical data | Can be reconfigured or rebuilt |
| sessions/2026/04/12/session-001-other-user-asked-about-deployment.jsonl | 726 bytes | LOW - Non-critical data | Can be reconfigured or rebuilt |
| sessions/2026/04/12/session-001-other-user-asked-about-deployment.jsonl | 726 bytes | LOW - Non-critical data | Can be reconfigured or rebuilt |
| templates/openclaw-agents.json | 802,706 bytes | LOW - Non-critical data | Can be reconfigured or rebuilt |
| templates/openclaw-agents.json | 802,706 bytes | LOW - Non-critical data | Can be reconfigured or rebuilt |
| templates/system-prompts.json | 2,236,759 bytes | LOW - Non-critical data | Can be reconfigured or rebuilt |
| templates/system-prompts.json | 2,236,759 bytes | LOW - Non-critical data | Can be reconfigured or rebuilt |

## 5. GATING LIST FOR CLOUD FEATURES

Analysis of which cloud features are gated on specific store migrations:

### taos.my relay subdomain (tsk-gqyv6z)

- **Requires Postgres**: True
- **Justification**: Multi-user agent identity and token management requires shared Postgres
- **Store dependencies**: 4 stores
  - AgentRegistryStore, AgentTokenStore, AuthRequestsStore, AgentScopeRequestsStore

### Account and subdomain provisioning (tsk-gqyv6z)

- **Requires Postgres**: True
- **Justification**: Multi-tenant contact sharing and hub coordination
- **Store dependencies**: 3 stores
  - ContactsStore, HubStore, AuthRequestsStore

### taOSgo (tsk-gqyv6z)

- **Requires Postgres**: False
- **Justification**: Can coexist with SQLite; no multi-tenant requirements
- **Store dependencies**: 3 stores
  - All user stores with project_id, DecisionStore, SystemEventStore

## 6. ZERO-LOSS PROCEDURE

Verification and rollback plan to ensure zero data loss:

### Verification Steps (in order)

1. **Row Count Verification**
   - Before migration: `SELECT COUNT(*) FROM <table>` for each target table
   - Store results in JSON manifest file
   - Run verification after migration attempt

2. **Content Hash Verification**
   - Compute SHA-256 hash of critical data per row (excluding auto-increment IDs)
   - Store hashes in verification manifest
   - Compare hashes pre- and post-migration

3. **Schema Comparison**
   - Verify target table schemas match expected Postgres schema
   - Check column types, constraints, and indexes
   - Ensure no data loss during schema migration

### Rollback Procedure

If any verification step fails:
1. Stop all incoming requests to the system
2. Immediately revert to SQLite stores using original schema
3. Restore original data from backup (if available)
4. Clear any partially migrated Postgres instances
5. Restart system with SQLite configuration
6. Document failure and investigate root cause

### Pre-Migration Safeguards

- Create full backup of all SQLite databases
- Implement feature flags to switch between SQLite and Postgres
- Monitor system health during migration
- Prepare rollback script for emergency use
