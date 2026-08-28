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
| ./tinyagentos/cluster/capability_map.py | CapabilityMap | False | False | False |
| ./tinyagentos/channels.py | ChannelStore | True | False | True |
| ./tinyagentos/chat/channel_store.py | ChatChannelStore | True | False | True |
| ./tinyagentos/chat/message_store.py | ChatMessageStore | True | True | True |
| ./tinyagentos/client_log_store.py | ClientLogStore | True | False | True |
| ./tinyagentos/cluster/pairing_store.py | ClusterPairingStore | False | False | False |
| ./tinyagentos/coding_sessions/store.py | CodingSessionStore | True | False | True |
| ./tinyagentos/coding_workspaces.py | CodingWorkspaceStore | False | False | True |
| ./tinyagentos/contacts_store.py | ContactsStore | False | True | True |
| ./tinyagentos/conversion.py | ConversionManager | False | False | True |
| ./tinyagentos/decisions/decision_store.py | DecisionStore | True | False | True |
| ./tinyagentos/design_docs.py | DesignStore | False | False | True |
| ./tinyagentos/desktop_settings.py | DesktopSettingsStore | True | False | False |
| ./tinyagentos/device_pair_requests_store.py | DevicePairRequestsStore | False | False | True |
| ./tinyagentos/device_store.py | DeviceStore | True | False | False |
| ./tinyagentos/projects/doc_review_store.py | DocReviewStore | True | False | True |
| ./tinyagentos/governance/policy_store.py | ExecutionPolicyStore | True | True | True |
| ./tinyagentos/expert_agents.py | ExpertAgentStore | False | True | True |
| ./tinyagentos/feedback_store.py | FeedbackStore | True | False | True |
| ./tinyagentos/github_identities.py | GitHubIdentitiesStore | False | False | True |
| ./tinyagentos/hub/store.py | HubStore | False | False | True |
| ./tinyagentos/install_registry.py | InstallRegistryStore | False | False | True |
| ./tinyagentos/installed_apps.py | InstalledAppsStore | False | False | False |
| ./tinyagentos/knowledge_store.py | KnowledgeStore | True | False | True |
| ./tinyagentos/library_store.py | LibraryStore | False | False | True |
| ./tinyagentos/license_acceptances_store.py | LicenseAcceptancesStore | True | False | False |
| ./tinyagentos/lora_store.py | LoraStore | False | False | True |
| ./tinyagentos/mcp/registry.py | MCPServerStore | True | False | True |
| ./tinyagentos/mail_store.py | MailAccountStore | True | False | True |
| ./tinyagentos/council/member_store.py | MemberStore | False | True | False |
| ./tinyagentos/metrics.py | MetricsStore | False | False | True |
| ./tinyagentos/notifications_push.py | NotificationPushStore | True | True | True |
| ./tinyagentos/notifications.py | NotificationStore | True | True | True |
| ./tinyagentos/office_docs.py | OfficeDocStore | False | False | True |
| ./tinyagentos/password_reset_store.py | PasswordResetStore | True | False | True |
| ./tinyagentos/chat/peer_outbox.py | PeerOutboxStore | False | False | True |
| ./tinyagentos/projects/canvas/store.py | ProjectCanvasStore | True | False | True |
| ./tinyagentos/projects/element_store.py | ProjectElementStore | True | True | True |
| ./tinyagentos/projects/invite_store.py | ProjectInviteStore | True | False | False |
| ./tinyagentos/projects/lists_store.py | ProjectListEntriesStore | True | True | True |
| ./tinyagentos/projects/lists_store.py | ProjectListsStore | True | True | True |
| ./tinyagentos/projects/notes_store.py | ProjectNotesStore | True | False | True |
| ./tinyagentos/projects/project_store.py | ProjectStore | True | False | True |
| ./tinyagentos/projects/task_store.py | ProjectTaskStore | True | True | True |
| ./tinyagentos/receipt_store.py | ReceiptStore | True | True | True |
| ./tinyagentos/relationships.py | RelationshipManager | True | False | True |
| ./tinyagentos/council/role_registry.py | RoleRegistry | False | False | False |
| ./tinyagentos/projects/routines_store.py | RoutineStore | True | False | True |
| ./tinyagentos/secrets.py | SecretsStore | True | False | True |
| ./tinyagentos/notes/shared_docs_store.py | SharedDocsStore | True | True | True |
| ./tinyagentos/shared_folders.py | SharedFolderManager | True | True | True |
| ./tinyagentos/skills.py | SkillStore | True | True | True |
| ./tinyagentos/music_songs.py | SongStore | False | False | True |
| ./tinyagentos/store_submissions.py | StoreSubmissionStore | False | False | True |
| ./tinyagentos/streaming.py | StreamingSessionStore | True | False | False |
| ./tinyagentos/projects/strike_store.py | StrikeStore | False | False | True |
| ./tinyagentos/events/store.py | SystemEventStore | False | True | False |
| ./tinyagentos/scheduler/task_scheduler.py | TaskScheduler | True | False | True |
| ./tinyagentos/themes/store.py | ThemeStore | False | False | False |
| ./tinyagentos/todo/todo_store.py | TodoStore | True | False | True |
| ./tinyagentos/training.py | TrainingManager | True | False | True |
| ./tinyagentos/user_memory.py | UserMemoryStore | True | False | True |
| ./tinyagentos/user_shares_store.py | UserSharesStore | True | True | True |
| ./tinyagentos/userspace/store.py | UserspaceAppStore | False | False | False |
| ./tinyagentos/userspace/data_store.py | UserspaceDataStore | False | False | False |
| ./tinyagentos/video_jobs.py | VideoJobStore | False | False | True |
| ./tinyagentos/web_sites.py | WebSiteStore | True | False | True |
| ./tinyagentos/cluster/worker_registry_store.py | WorkerRegistryStore | False | False | False |
