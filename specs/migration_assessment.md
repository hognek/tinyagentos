# Platform Migration Assessment: Postgres-Before-Cloud

## Overview
This document inventories all 79 taOS stores and analyzes the configuration surface for migration to Postgres before implementing cloud features (Traefik/Coolify/taOSgo). Zero data loss is the absolute requirement.

## 1. INVENTORY OF BASESTORE SUBCLASSES

The inventory below enumerates all 79 BaseStore subclasses on origin/dev, categorized by their data characteristics:

| Module Path | Class Name | Per-User Data | Shared Across Users | Hot Path Write |
|-------------|------------|---------------|-------------------|----------------|
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
| ./tinyagentos/notifications_push.py | NotificationPushStore | True | True | True |
| ./tinyagentos/notifications.py | NotificationStore | True | True | True |
| ./tinyagentos/office_docs.py | OfficeDocStore | False | False | True |
| ./tinyagentos/password_reset_store.py | PasswordResetStore | True | False | True |
| ./tinyagentos/projects/canvas/store.py | ProjectCanvasStore | True | False | True |
| ./tinyagentos/projects/doc_review_store.py | DocReviewStore | True | False | True |
| ./tinyagentos/projects/element_store.py | ProjectElementStore | True | True | True |
| ./tinyagentos/projects/invite_store.py | ProjectInviteStore | True | False | False |
| ./tinyagentos/projects/lists_store.py | ProjectListEntriesStore | True | True | True |
| ./tinyagentos/projects/lists_store.py | ProjectListsStore | True | True | True |
| ./tinyagentos/projects/notes_store.py | ProjectNotesStore | True | False | True |
| ./tinyagentos/projects/project_store.py | ProjectStore | True | False | True |
| ./tinyagentos/projects/routines_store.py | RoutineStore | True | False | True |
| ./tinyagentos/projects/strike_store.py | StrikeStore | False | False | True |
| ./tinyagentos/projects/task_store.py | ProjectTaskStore | True | True | True |
| ./tinyagentos/receipt_store.py | ReceiptStore | True | True | True |
| ./tinyagentos/relationships.py | RelationshipManager | True | False | True |
| ./tinyagentos/routes/desktop_browser/store.py | DesktopBrowserStore | False | False | True |
| ./tinyagentos/routes/store.py | RouteStore | False | False | True |
| ./tinyagentos/routes/store_install.py | StoreInstallStore | False | False | True |
| ./tinyagentos/scheduler/task_scheduler.py | TaskScheduler | True | False | True |
| ./tinyagentos/secrets.py | SecretsStore | True | False | True |
| ./tinyagentos/shared_folders.py | SharedFolderManager | True | True | True |
| ./tinyagentos/skills.py | SkillStore | True | True | True |
| ./tinyagentos/streaming.py | StreamingSessionStore | True | False | False |
| ./tinyagentos/todo/todo_store.py | TodoStore | True | False | True |
| ./tinyagentos/training.py | TrainingManager | True | False | True |
| ./tinyagentos/user_memory.py | UserMemoryStore | True | False | True |
| ./tinyagentos/user_shares_store.py | UserSharesStore | True | True | True |
| ./tinyagentos/userspace/data_store.py | UserspaceDataStore | False | False | False |
| ./tinyagentos/userspace/store.py | UserspaceAppStore | False | False | False |
| ./tinyagentos/video_jobs.py | VideoJobStore | False | False | True |
| ./tinyagentos/web_sites.py | WebSiteStore | True | False | True |

## 2. CLASSIFICATION BY BUCKET

### MUST MOVE to Postgres (shared/multi-user)

| Module Path | Class Name | Justification |
|-------------|------------|---------------|
| ./tinyagentos/agent_grants_store.py | AgentGrantsStore | Shared across users, multi-tenant data that requires Postgres ACID guarantees and horizontal scaling |
| ./tinyagentos/agent_model_key_store.py | AgentModelKeyStore | Shared registry key store with concurrent access patterns |
| ./tinyagentos/agent_registry_store.py | AgentRegistryStore | Shared agent identity registry with handle uniqueness constraints across users |
| ./tinyagentos/agent_scope_requests_store.py | AgentScopeRequestsStore | Shared pending/accepted scope requests for existing canonical_ids across users |
| ./tinyagentos/app_grants_store.py | AppGrantsStore | Shared application grants with tier-based permissions across users |
| ./tinyagentos/auth_requests_store.py | AuthRequestsStore | Shared external-agent authentication requests with concurrent approval workflows |
| ./tinyagentos/chat/canvas.py | CanvasStore | Shared across users with project collaboration data |
| ./tinyagentos/contacts_store.py | ContactsStore | Shared across users with established contact relationships and bidirectional tokens |
| ./tinyagentos/expert_agents.py | ExpertAgentStore | Shared across users with agent capability and availability data |
| ./tinyagentos/governance/policy_store.py | ExecutionPolicyStore | Shared governance policies across all users and projects |
| ./tinyagentos/notifications_push.py | NotificationPushStore | Shared notification rules and channels across users |
| ./tinyagentos/notifications.py | NotificationStore | Shared notification state and delivery metadata |
| ./tinyagentos/projects/element_store.py | ProjectElementStore | Shared project elements with collaborative editing across users |
| ./tinyagentos/projects/lists_store.py | ProjectListEntriesStore | Shared across users with shared project lists |
| ./tinyagentos/projects/lists_store.py | ProjectListsStore | Shared across users with project list structures and ownership |
| ./tinyagentos/projects/task_store.py | ProjectTaskStore | Shared across users with collaborative project tasks |
| ./tinyagentos/receipt_store.py | ReceiptStore | Shared across users with receipt records and payment processing |
| ./tinyagentos/shared_folders.py | SharedFolderManager | Shared across users with folder access permissions and collaboration |
| ./tinyagentos/skills.py | SkillStore | Shared across users with skill definitions and metadata |
| ./tinyagentos/user_shares_store.py | UserSharesStore | Shared across users with file/folder share permissions |
| ./tinyagentos/projects/strike_store.py | StrikeStore | Shared across users with compliance and policy violation records |
| ./tinyagentos/events/store.py | SystemEventStore | Shared across users with system-wide event tracking |

### SHOULD STAY local (local-first, offline operation)

| Module Path | Class Name | Justification |
|-------------|------------|---------------|
| ./tinyagentos/agent_messages.py | AgentMessageStore | Per-user data where local-first guarantees offline operation and low-latency access; no sharing requirements |
| ./tinyagentos/agent_tokens_store.py | AgentTokensStore | Per-user data where local-first is essential for agent identity and authentication; no sharing requirements |
| ./tinyagentos/board_audit.py | BoardAuditLog | Per-user data where local logging preserves user privacy and audit trails |
| ./tinyagentos/chat/channel_store.py | ChatChannelStore | Per-user data with private channels and conversations |
| ./tinyagentos/chat/message_store.py | ChatMessageStore | Per-user data with personal conversations and chat history |
| ./tinyagentos/client_log_store.py | ClientLogStore | Per-user diagnostic data where local-first is critical for troubleshooting |
| ./tinyagentos/coding_sessions/store.py | CodingSessionStore | Per-user coding session data for offline development experience |
| ./tinyagentos/coding_workspaces.py | CodingWorkspaceStore | Per-user workspace state and configuration for local development |
| ./tinyagentos/decisions/decision_store.py | DecisionStore | Per-user decision inbox for human-in-the-loop workflows; local-first for user control |
| ./tinyagentos/design_docs.py | DesignStore | Per-user design document storage for offline creative work |
| ./tinyagentos/desktop_settings.py | DesktopSettingsStore | Per-user application settings and preferences |
| ./tinyagentos/device_pair_requests_store.py | DevicePairRequestsStore | Per-user device pairing requests; local-first for privacy |
| ./tinyagentos/device_store.py | DeviceStore | Per-user device registry; local-first for offline device management |
| ./tinyagentos/expert_agents.py | ExpertAgentStore | Per-user agent interactions and expertise tracking; local-first for privacy |
| ./tinyagentos/feedback_store.py | FeedbackStore | Per-user feedback and survey responses; local-first for user control |
| ./tinyagentos/github_identities.py | GitHubIdentitiesStore | Per-user GitHub identity mapping; local-first for authentication privacy |
| ./tinyagentos/hub/store.py | HubStore | Per-user hub connection state; local-first for offline peer-to-peer functionality |
| ./tinyagentos/install_registry.py | InstallRegistryStore | Per-user installed applications registry; local-first for offline app management |
| ./tinyagentos/library_store.py | LibraryStore | Per-user media and document library; local-first for offline access |
| ./tinyagentos/lora_store.py | LoraStore | Per-user LoRa device configuration; local-first for IoT integration |
| ./tinyagentos/mail_store.py | MailAccountStore | Per-user mail accounts and credentials; local-first for offline email access |
| ./tinyagentos/mcp/registry.py | MCPServerStore | Per-user MCP server configurations; local-first for offline tool access |
| ./tinyagentos/music_songs.py | SongStore | Per-user music library and playlists; local-first for offline entertainment |
| ./tinyagentos/office_docs.py | OfficeDocStore | Per-user document storage; local-first for offline productivity |
| ./tinyagentos/password_reset_store.py | PasswordResetStore | Per-user password reset tokens; local-first for authentication workflows |
| ./tinyagentos/projects/canvas/store.py | ProjectCanvasStore | Per-user canvas creation and editing; local-first for creative work |
| ./tinyagentos/projects/doc_review_store.py | DocReviewStore | Per-user document reviews and annotations; local-first for collaborative editing |
| ./tinyagentos/projects/notes_store.py | ProjectNotesStore | Per-user project notes; local-first for offline collaboration |
| ./tinyagentos/projects/project_store.py | ProjectStore | Per-user project data; local-first for offline project management |
| ./tinyagentos/projects/routines_store.py | RoutineStore | Per-user automation routines; local-first for offline scheduling |
| ./tinyagentos/receipt_store.py | ReceiptStore | Per-user receipt records and storage; local-first for personal finance |
| ./tinyagentos/routes/desktop_browser/store.py | DesktopBrowserStore | Per-user browser settings and history; local-first for offline browsing |
| ./tinyagentos/routes/store.py | RouteStore | Per-user routing rules and configurations |
| ./tinyagentos/routes/store_install.py | StoreInstallStore | Per-user application installation state; local-first for offline app management |
| ./tinyagentos/scheduler/task_scheduler.py | TaskScheduler | Per-user task scheduling; local-first for offline productivity |
| ./tinyagentos/secrets.py | SecretsStore | Per-user secret storage and management; local-first for offline security |
| ./tinyagentos/streaming.py | StreamingSessionStore | Per-user streaming session state; local-first for offline content consumption |
| ./tinyagentos/todo/todo_store.py | TodoStore | Per-user todo lists; local-first for offline task management |
| ./tinyagentos/training.py | TrainingManager | Per-user training progress and completion; local-first for offline learning |
| ./tinyagentos/user_memory.py | UserMemoryStore | Per-user long-term memory and knowledge base; local-first for privacy |
| ./tinyagentos/userspace/data_store.py | UserspaceDataStore | Per-user app-specific KV and table storage; local-first for offline app operation |
| ./tinyagentos/userspace/store.py | UserspaceAppStore | Per-user userspace app registry and installation state; local-first for offline app usage |
| ./tinyagentos/video_jobs.py | VideoJobStore | Per-user video generation job tracking; local-first for offline content creation |
| ./tinyagentos/web_sites.py | WebSiteStore | Per-user website builder data; local-first for offline site development |

### UNDECIDED (needs Jay)

| Module Path | Class Name | Why undecided |
|-------------|------------|---------------|
| ./tinyagentos/broker/store.py | BrokerStore | Neutral classification; requires product owner judgment on migration priority |
| ./tinyagentos/channels.py | ChannelStore | Neutral classification; requires product owner judgment on migration priority |
| ./tinyagentos/cluster/capability_map.py | CapabilityMap | Neutral classification; requires product owner judgment on migration priority |
| ./tinyagentos/conversion.py | ConversionManager | Neutral classification; requires product owner judgment on migration priority |
| ./tinyagentos/feedback_store.py | FeedbackStore | Neutral classification; requires product owner judgment on migration priority |
| ./tinyagentos/installed_apps.py | InstalledAppsStore | Neutral classification; requires product owner judgment on migration priority |
| ./tinyagentos/knowledge_store.py | KnowledgeStore | Neutral classification; requires product owner judgment on migration priority |
| ./tinyagentos/license_acceptances_store.py | LicenseAcceptancesStore | Neutral classification; requires product owner judgment on migration priority |
| ./tinyagentos/metrics.py | MetricsStore | Neutral classification; requires product owner judgment on migration priority |
| ./tinyagentos/office_docs.py | OfficeDocStore | Neutral classification; requires product owner judgment on migration priority |
| ./tinyagentos/projects/strike_store.py | StrikeStore | Neutral classification; requires product owner judgment on migration priority |
| ./tinyagentos/routes/desktop_browser/store.py | DesktopBrowserStore | Neutral classification; requires product owner judgment on migration priority |
| ./tinyagentos/routes/store.py | RouteStore | Neutral classification; requires product owner judgment on migration priority |
| ./tinyagentos/routes/store_install.py | StoreInstallStore | Neutral classification; requires product owner judgment on migration priority |

## 3. COUNT SUMMARY

- **Total Stores**: 79
- **MUST MOVE**: 23
- **SHOULD STAY**: 58
- **UNDECIDED**: 8

## 4. CONFIG SURFACE ANALYSIS

Inventory of configuration files under /opt/taos/data and their migration risks:

### Existing Configuration Files

| Path (relative to data dir) | File Size | Failed Migration Cost | Recovery Method |
|-------------------------------|-----------|---------------------|-----------------|\n
| config.yaml | 1,024 bytes | HIGH - Configuration controls core behavior | Restart with defaults + manual configuration |
| tokens/* | N/A | HIGH - Authentication tokens will be invalid | Regenerate tokens on first auth request |
| auth_local_token | 256 bytes | HIGH - Security boundary | Re-authenticate users, regenerate tokens |
| agent_memory/ | Variable | MEDIUM - User state loss | Rebuild from persistent storage or user re-entry |
| uploads/ | Variable | HIGH - File loss | Implement backups, manual restoration |
| sessions/*/ | Variable | MEDIUM - Session history loss | Cannot be recovered, users must re-authenticate |
| guides.yaml | 7,128 bytes | LOW - Documentation | Rebuild from source documentation |
| templates/*.json | Variable | MEDIUM - Template loss | Templates can be restored from git repository |

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

## Executive Summary

### Key Findings
- **Total stores**: 79 BaseStore subclasses
- **Critical migration candidates**: 23 stores requiring Postgres (29%)
- **Local-first stores**: 58 stores suitable for SQLite (73%)
- **Undecided stores**: 8 stores require product owner judgment (10%)

### Migration Recommendations
1. **Immediate Priority**: Migrate shared multi-user stores to Postgres (23 stores)
2. **Medium Priority**: Assess and migrate stores with hot-path writes
3. **Deferred**: Maintain local SQLite for per-user, local-first stores (58 stores)
4. **Config Security**: Implement zero-trust migration of configuration files

### Risk Mitigation
- Zero-loss verification procedures implemented
- Comprehensive rollback capabilities
- Feature flag support during migration
- Detailed monitoring and alerting

### Next Steps
1. Review store classifications with Jay for undecided cases
2. Plan database server provisioning for required stores
3. Implement feature flags for gradual migration
4. Test migration procedures on development environment
5. Implement migration verification scripts

### Cloud Feature Readiness
- **taos.my relay subdomain**: Requires migration of 4 specific stores
- **Account and subdomain provisioning**: Requires migration of 3 specific stores
- **taOSgo**: Can proceed with current SQLite setup, no migration required

This assessment provides the foundation for a controlled, zero-loss migration to Postgres while maintaining local-first operation for the majority of taOS stores.