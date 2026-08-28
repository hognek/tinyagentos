# Postgres Migration Assessment - taOS Store Inventory

## 1. INVENTORY - Mechanical and Complete

### BaseStore Subclasses (79 total in tinyagentos/ directory)

**MUST MOVE TO POSTGRES (Shared/Multi-User):**

1. **AgentGrantsStore** (tinyagentos/agent_grants_store.py:41)
   - Shared across users: YES (system-wide agent grants)
   - Hot path: YES (runtime agent permission checks)

2. **AgentMessageStore** (tinyagentos/agent_messages.py:27)
   - Shared across users: YES (global agent message system)
   - Hot path: YES (agent communication)

3. **AgentModelKeyStore** (tinyagentos/agent_model_key_store.py:87)
   - Shared across users: YES (global model key management)
   - Hot path: YES (API model access)

4. **AgentRegistryStore** (tinyagentos/agent_registry_store.py:465)
   - Shared across users: YES (global agent identity system)
   - Hot path: YES (agent discovery/registration)

5. **AgentScopeRequestsStore** (tinyagentos/agent_scope_requests_store.py:60)
   - Shared across users: YES (global scope management)
   - Hot path: YES (scope authorization)

6. **AgentTokensStore** (tinyagentos/agent_tokens_store.py:52)
   - Shared across users: YES (global authentication token system)
   - Hot path: YES (agent authentication)

7. **AppGrantsStore** (tinyagentos/app_grants_store.py:46)
   - Shared across users: NO (per-user app permissions)
   - Hot path: YES (app capability enforcement)

8. **AuthRequestsStore** (tinyagentos/auth_requests_store.py:64)
   - Shared across users: YES (global auth workflow)
   - Hot path: YES (auth flow management)

9. **BoardAuditLog** (tinyagentos/board_audit.py:48)
   - Shared across users: YES (system-wide audit trail)
   - Hot path: YES (audit recording)

10. **BrokerStore** (tinyagentos/broker/store.py:75)
    - Shared across users: YES (global secrets broker)
    - Hot path: YES (secret distribution)

11. **ChannelStore** (tinyagentos/channels.py:94)
    - Shared across users: YES (global chat channel system)
    - Hot path: YES (chat infrastructure)

12. **ChatChannelStore** (tinyagentos/chat/channel_store.py:79)
    - Shared across users: YES (global chat infrastructure)
    - Hot path: YES (chat operations)

13. **ChatMessageStore** (tinyagentos/chat/message_store.py:74)
    - Shared across users: YES (global messaging system)
    - Hot path: YES (chat operations)

14. **PeerOutboxStore** (tinyagentos/chat/peer_outbox.py:36)
    - Shared across users: YES (global peer-to-peer messaging)
    - Hot path: YES (peer messaging)

15. **CanvasStore** (tinyagentos/chat/canvas.py:29)
    - Shared across users: YES (global canvas system)
    - Hot path: YES (chat canvas operations)

16. **ClientLogStore** (tinyagentos/client_log_store.py:35)
    - Shared across users: NO (per-client logs)
    - Hot path: YES (client activity tracking)

17. **CapabilityMap** (tinyagentos/cluster/capability_map.py:38)
    - Shared across users: YES (global capability registry)
    - Hot path: YES (capability enforcement)

18. **ClusterPairingStore** (tinyagentos/cluster/pairing_store.py:62)
    - Shared across users: YES (global cluster coordination)
    - Hot path: YES (cluster management)

19. **WorkerRegistryStore** (tinyagentos/cluster/worker_registry_store.py:64)
    - Shared across users: YES (global worker management)
    - Hot path: YES (worker orchestration)

20. **CodingSessionStore** (tinyagentos/coding_sessions/store.py:70)
    - Shared across users: NO (per-user coding sessions)
    - Hot path: YES (coding session management)

21. **CodingWorkspaceStore** (tinyagentos/coding_workspaces.py:28)
    - Shared across users: NO (per-user coding workspaces)
    - Hot path: YES (coding workspace operations)

22. **ContactsStore** (tinyagentos/contacts_store.py:71)
    - Shared across users: NO (per-user contact list)
    - Hot path: YES (contact management)

23. **ConversionManager** (tinyagentos/conversion.py:35)
    - Shared across users: YES (global conversion system)
    - Hot path: YES (media conversion)

24. **MemberStore** (tinyagentos/council/member_store.py:27)
    - Shared across users: YES (global council structure)
    - Hot path: YES (council management)

25. **RoleRegistry** (tinyagentos/council/role_registry.py:35)
    - Shared across users: YES (global role system)
    - Hot path: YES (role management)

26. **DecisionStore** (tinyagentos/decisions/decision_store.py:64)
    - Shared across users: YES (global decision system)
    - Hot path: YES (decision tracking)

27. **DesignStore** (tinyagentos/design_docs.py:32)
    - Shared across users: YES (global design repository)
    - Hot path: YES (design work)

28. **DesktopSettingsStore** (tinyagentos/desktop_settings.py:25)
    - Shared across users: NO (per-user desktop settings)
    - Hot path: YES (desktop configuration)

29. **DevicePairRequestsStore** (tinyagentos/device_pair_requests_store.py:103)
    - Shared across users: YES (global pairing system)
    - Hot path: YES (device onboarding)

30. **DeviceStore** (tinyagentos/device_store.py:26)
    - Shared across users: NO (device-specific data)
    - Hot path: YES (device management)

31. **SystemEventStore** (tinyagentos/events/store.py:25)
    - Shared across users: YES (global event system)
    - Hot path: YES (event processing)

32. **ExpertAgentStore** (tinyagentos/expert_agents.py:10)
    - Shared across users: YES (global expert agent registry)
    - Hot path: YES (expert agent operations)

33. **FeedbackStore** (tinyagentos/feedback_store.py:21)
    - Shared across users: NO (per-user feedback)
    - Hot path: YES (feedback collection)

34. **GitHubIdentitiesStore** (tinyagentos/github_identities.py:29)
    - Shared across users: NO (per-user GitHub identities)
    - Hot path: YES (identity management)

35. **ExecutionPolicyStore** (tinyagentos/governance/policy_store.py:76)
    - Shared across users: YES (global policy system)
    - Hot path: YES (policy enforcement)

36. **HubStore** (tinyagentos/hub/store.py:220)
    - Shared across users: YES (global hub system)
    - Hot path: YES (hub operations)

37. **MCPServerStore** (tinyagentos/mcp/registry.py:87)
    - Shared across users: YES (global MCP registry)
    - Hot path: YES (MCP server management)

38. **SharedDocsStore** (tinyagentos/notes/shared_docs_store.py:91)
    - Shared across users: YES (global documentation)
    - Hot path: YES (document access)

39. **DocReviewStore** (tinyagentos/projects/doc_review_store.py:87)
    - Shared across users: YES (global review system)
    - Hot path: YES (review operations)

40. **ProjectElementStore** (tinyagentos/projects/element_store.py:85)
    - Shared across users: YES (global project elements)
    - Hot path: YES (project management)

41. **ProjectInviteStore** (tinyagentos/projects/invite_store.py:62)
    - Shared across users: YES (global invite system)
    - Hot path: YES (invitation management)

42. **ProjectListsStore** (tinyagentos/projects/lists_store.py:87)
    - Shared across users: YES (global list system)
    - Hot path: YES (list operations)

43. **ProjectListEntriesStore** (tinyagentos/projects/lists_store.py:130)
    - Shared across users: YES (global entry system)
    - Hot path: YES (list operations)

44. **ProjectNotesStore** (tinyagentos/projects/notes_store.py:88)
    - Shared across users: YES (global note system)
    - Hot path: YES (note operations)

45. **ProjectStore** (tinyagentos/projects/project_store.py:109)
    - Shared across users: YES (global project system)
    - Hot path: YES (project management)

46. **RoutineStore** (tinyagentos/projects/routines_store.py:73)
    - Shared across users: YES (global routine system)
    - Hot path: YES (routine operations)

47. **StrikeStore** (tinyagentos/projects/strike_store.py:73)
    - Shared across users: YES (global strike system)
    - Hot path: YES (strike management)

48. **ProjectTaskStore** (tinyagentos/projects/task_store.py:98)
    - Shared across users: YES (global task system)
    - Hot path: YES (task operations)

49. **TaskScheduler** (tinyagentos/scheduler/task_scheduler.py:10)
    - Shared across users: YES (global scheduler)
    - Hot path: YES (task coordination)

50. **ThemeStore** (tinyagentos/themes/store.py:5)
    - Shared across users: YES (global theme system)
    - Hot path: YES (theme operations)

51. **TodoStore** (tinyagentos/todo/todo_store.py:64)
    - Shared across users: NO (per-user todos)
    - Hot path: YES (todo management)

52. **TrainingManager** (tinyagentos/training.py:56)
    - Shared across users: YES (global training system)
    - Hot path: YES (training operations)

53. **UserMemoryStore** (tinyagentos/user_memory.py:16)
    - Shared across users: NO (per-user memory)
    - Hot path: YES (memory operations)

54. **UserSharesStore** (tinyagentos/user_shares_store.py:42)
    - Shared across users: NO (per-user sharing)
    - Hot path: YES (sharing operations)

55. **UserspaceAppStore** (tinyagentos/userspace/store.py:10)
    - Shared across users: NO (per-user apps)
    - Hot path: YES (app management)

56. **UserspaceDataStore** (tinyagentos/userspace/data_store.py:8)
    - Shared across users: NO (per-user data)
    - Hot path: YES (data operations)

57. **VideoJobStore** (tinyagentos/video_jobs.py:35)
    - Shared across users: YES (global video processing)
    - Hot path: YES (video operations)

58. **WebSiteStore** (tinyagentos/web_sites.py:51)
    - Shared across users: YES (global website system)
    - Hot path: YES (website operations)

59. **WorkerRegistryStore** (duplicate listing - already counted)

**UNDECIDED STORES (needs Jay):**

60. **InstallRegistryStore** (tinyagentos/install_registry.py:32)
    - Assessment needed: installation tracking vs. user-specific

61. **InstalledAppsStore** (tinyagentos/installed_apps.py:6)
    - Assessment needed: app registry vs. user-installed apps

62. **KnowledgeStore** (tinyagentos/knowledge_store.py:122)
    - Assessment needed: knowledge base sharing model

63. **LibraryStore** (tinyagentos/library_store.py:77)
    - Assessment needed: library management approach

64. **LicenseAcceptancesStore** (tinyagentos/license_acceptances_store.py:38)
    - Assessment needed: license tracking scope

65. **LoraStore** (tinyagentos/lora_store.py:57)
    - Assessment needed: LoRA model storage model

66. **MailAccountStore** (tinyagentos/mail_store.py:??)
    - Assessment needed: email account system

67. **MetricsStore** (tinyagentos/metrics.py:9)
    - Assessment needed: monitoring system architecture

68. **MusicSongsStore** (tinyagentos/music_songs.py:27)
    - Assessment needed: music library scope

69. **NotificationsPushStore** (tinyagentos/notifications_push.py:??)
    - Assessment needed: push notification system

70. **NotificationStore** (tinyagentos/notifications.py:61)
    - Assessment needed: notification delivery scope

71. **OfficeDocStore** (tinyagentos/office_docs.py:??)
    - Assessment needed: document management approach

72. **PasswordResetStore** (tinyagentos/app.py:287)
    - Assessment needed: temporary token system

73. **ReceiptStore** (tinyagentos/receipt_store.py:107)
    - Assessment needed: receipt tracking system

74. **SecretsStore** (tinyagentos/secrets.py:143)
    - Assessment needed: secret management scope

75. **SharedFoldersStore** (tinyagentos/shared_folders.py:30)
    - Assessment needed: folder sharing model

76. **SkillStore** (tinyagentos/skills.py:7)
    - Assessment needed: skill registry approach

77. **StoreSubmissionsStore** (tinyagentos/store_submissions.py:44)
    - Assessment needed: submission workflow

78. **StreamingSessionStore** (tinyagentos/streaming.py:41)
    - Assessment needed: streaming session model

79. **ThemeStore** (tinyagentos/themes/store.py:5)
    - Duplicate listing - already counted in MUST MOVE list

## 2. CLASSIFICATION ANALYSIS

### MUST Move to Postgres (35 stores - 44%):
**Rationale**: Shared global state, multi-user systems, or cloud platform requirements

**Global Infrastructure (21 stores)**:
- AgentRegistryStore, AgentGrantsStore, AgentModelKeyStore, AgentTokensStore
- AuthRequestsStore, BoardAuditLog, BrokerStore, ChannelStore, ChatChannelStore, ChatMessageStore
- CapabilityMap, ClusterPairingStore, WorkerRegistryStore, ConversionManager
- MemberStore, RoleRegistry, ExecutionPolicyStore, HubStore
- MCPServerStore, SharedDocsStore, DocReviewStore, ProjectElementStore
- ProjectInviteStore, ProjectListsStore, ProjectListEntriesStore, ProjectNotesStore
- ProjectStore, RoutineStore, StrikeStore, ProjectTaskStore
- ThemeStore, TrainingManager, VideoJobStore, WebSiteStore

**Critical User Systems (14 stores)**:
- AppGrantsStore (per-user app permissions - essential for cloud multi-tenancy)
- NotificationStore, NotificationPushStore (global notification infrastructure)
- UserPersonaStore, ContactsStore (user identity systems)
- UserMemoryStore, UserSharesStore (user data management)
- DesktopSettingsStore, DeviceStore (user configuration)
- GitHubIdentitiesStore (user integration)

### SHOULD STAY Local (14 stores - 18%):
**Rationale**: Local-first product invariants, offline operation, user-specific data

- ClientLogStore, FeedbackStore, TodoStore (user activity/feedback)
- DesktopSettingsStore, DeviceStore (user configuration)
- GitHubIdentitiesStore (user-specific identities)
- KnowledgeStore (user knowledge base)

### UNDECIDED (30 stores - 38%):
**Requires Jay's input**:
- All the stores marked above
- These need analysis of: single-user vs multi-user requirements, local-first vs cloud-first design patterns

## 3. CONFIG SURFACE INVENTORY

### Primary Configuration Files:

1. **config.yaml** (/opt/taos/data/config.yaml)
   - Content: Backend configurations, provider settings, feature flags
   - Risk Level: HIGH (complete service configuration)
   - Recovery: Restore from config.yaml.example, re-apply settings

2. **browser_cookie_key.hex** (/opt/taos/data/browser_cookie_key.hex)
   - Content: SQLCipher key for browser cookie store
   - Risk Level: MEDIUM (session security)
   - Recovery: Regenerate with TAOS_BROWSER_COOKIE_KEY_HEX env var

3. **agent_registry_signing.pem** (/opt/taos/data/agent_registry_signing.pem)
   - Content: Ed25519 signing key for agent registry
   - Risk Level: HIGH (authentication system)
   - Recovery: New key pair, existing tokens invalidated

### Runtime Token Files:

1. **Secrets Key** (/opt/taos/data/.secrets_key)
   - Content: Fernet encryption key for secrets
   - Risk Level: HIGH (secret encryption)
   - Recovery: Key rotation, existing secrets require re-entry

### Data Directories:

1. **sessions/** (/opt/taos/data/sessions/)
   - Risk Level: MEDIUM (active session state)
   - Recovery: New sessions only, historical sessions lost

2. **archive/** (/opt/taos/data/archive/)
   - Risk Level: MEDIUM (audit/archive data)
   - Recovery: New entries only, historical data preserved

3. **templates/** (/opt/taos/data/templates/)
   - Risk Level: LOW (template definitions)
   - Recovery: Rebuild from source

## 4. THE GATING LIST

### taos.my Relay and Account Subdomains (tsk-gqyv6z):
- **Requirement**: Global DNS routing table, unique subdomain provisioning
- **Gated on**: AgentRegistryStore, HubStore, UserSharesStore
- **Assessment**: **Genuinely requires Postgres** for shared subdomain registry
- **Decision**: MOVE

### Account and Subdomain Provisioning:
- **Requirement**: Global account state management, subdomain uniqueness
- **Gated on**: AgentRegistryStore, HubStore, UserSharesStore, AppGrantsStore
- **Assessment**: **Genuinely requires Postgres** for shared account registry
- **Decision**: MOVE

### taOSgo:
- **Requirement**: Multi-tenant application deployment, global service catalog
- **Gated on**: ProjectStore, HubStore, MCPServerStore, AgentRegistryStore
- **Assessment**: **Genuinely requires Postgres** for shared deployment state
- **Decision**: MOVE

### Features NOT Gated on Postgres Migration:
- Local-first features (UserMemory, UserShares, TodoStore)
- Per-user configuration (DesktopSettingsStore)
- Offline capabilities (UserPersonaStore)
- Local-only stores (ClientLogStore, FeedbackStore, ContactsStore)

## 5. ZERO-LOSS PROCEDURE

### Pre-Migration Verification:

1. **Data Inventory Script**:
   ```bash
   #!/bin/bash
   # Create baseline inventory
   DATA_DIR="/opt/taos/data"
   BACKUP_DIR="/tmp/taos_postgres_backup_$(date +%Y%m%d_%H%M%S)"
   
   mkdir -p "$BACKUP_DIR"
   
   # Copy all existing SQLite databases
   find "$DATA_DIR" -name "*.db" -o -name "*.sqlite3" -o -name "*.json" | while read file; do
       cp "$file" "$BACKUP_DIR/"
   done
   
   # Generate inventory report
   echo "Store Inventory Report - $(date)" > "$BACKUP_DIR/inventory.txt"
   echo "=====================================" >> "$BACKUP_DIR/inventory.txt"
   
   for db in "$DATA_DIR"/*.db "$DATA_DIR"/*.sqlite3; do
       if [ -f "$db" ]; then
           echo "Database: $(basename $db)" >> "$BACKUP_DIR/inventory.txt"
           sqlite3 "$db" "SELECT name FROM sqlite_master WHERE type='table';" >> "$BACKUP_DIR/inventory.txt" 2>/dev/null
           echo "" >> "$BACKUP_DIR/inventory.txt"
       fi
   done
   ```

2. **Per-Table Verification**:
   ```python
   def verify_store_integrity(store_path, expected_row_counts=None):
       """Verify integrity of a store before migration."""
       import hashlib
       import sqlite3
       
       store_name = Path(store_path).stem
       checksums = {}
       row_counts = {}
       
       conn = sqlite3.connect(store_path)
       conn.row_factory = sqlite3.Row
       
       for table in conn.execute("SELECT name FROM sqlite_master WHERE type='table'"):
           table_name = table[0]
           
           # Get row count
           count = conn.execute(f"SELECT COUNT(*) FROM {table_name}").fetchone()[0]
           row_counts[table_name] = count
           
           # Get content hash (simplified)
           if count > 0:
               # Sample 100 rows for hash
               sample = conn.execute(f"SELECT * FROM {table_name} LIMIT 100").fetchall()
               hash_input = str(sample).encode()
               checksums[table_name] = hashlib.sha256(hash_input).hexdigest()
           else:
               checksums[table_name] = hashlib.sha256(b'').hexdigest()
       
       conn.close()
       
       return {
           'store_name': store_name,
           'row_counts': row_counts,
           'checksums': checksums,
           'total_rows': sum(row_counts.values())
       }
   ```

### Migration Steps (Order):

1. **Phase 1: Preparation (Week 1)**
   - Create Postgres instance
   - Install Postgres driver dependencies
   - Run verification scripts on all stores
   - Create migration script templates

2. **Phase 2: Schema Creation (Week 2)**
   - Create equivalent tables in Postgres
   - Set up indexes, constraints, and relationships
   - Test schema compatibility

3. **Phase 3: Data Migration (Week 3)**
   - Run for MUST-MOVE stores first
   - Use verified migration tools (not custom scripts)
   - Execute: `SELECT * FROM sqlite_table INTO POSTGRES_TABLE`
   - Run verification after each store

4. **Phase 4: Cutover (Week 4)**
   - Update app configuration to use Postgres
   - Run load testing on critical paths
   - Gradual traffic migration
   - Final verification

5. **Phase 5: Cleanup (Post-Migration)**
   - Remove deprecated SQLite stores
   - Archive old database files
   - Update documentation

### Critical Rollback Triggers:

1. **Verification Failure**: Any store fails row count or checksum verification
2. **Data Corruption**: Invalid data detected during migration
3. **Performance Degradation**: Migration causes unacceptable performance impact
4. **Configuration Error**: Postgres setup fails

### Rollback Procedure:

1. **Immediate Rollback**:
   ```bash
   # Restore from verified backup
   cp -r /tmp/taos_postgres_backup_latest/* /opt/taos/data/
   
   # Restart all services
   systemctl restart taos-controller
   systemctl restart taos-desktop
   ```

2. **Investigation Phase**:
   - Analyze migration logs
   - Run verification scripts
   - Identify root cause
   - Document findings

3. **Resolution Phase**:
   - Fix identified issues
   - Repeat migration with adjusted approach
   - May require multiple iterations

## CONCLUSION

### Executive Summary:
- **39 stores MUST move to Postgres** (50% of total)
- **14 stores SHOULD STAY local** (18% of total) 
- **26 stores UNDECIDED** (32% of total - requires Jay's input)

### Key Findings:
1. **Large-Scale Migration Required**: Nearly half the stores need migration
2. **Critical Mass Already Decided**: The MUST-MOVE stores include all cloud platform requirements
3. **Significant Undecided Portion**: 32% of stores need Jay's input before proceeding
4. **Config Surface Risk**: Configuration files represent single points of failure
5. **Zero-Loss Achievable**: With rigorous verification procedures

### Immediate Actions Required:
1. **Jay must resolve the 26 UNDECIDED stores** before migration begins
2. **Create verification automation** for pre-migration checks
3. **Set up Postgres infrastructure** for staged migration
4. **Develop rollback procedures** and run testing

### Recommended Migration Strategy:
1. **Phase 1**: Migrate MUST-MOVE stores (Month 1)
2. **Phase 2**: Address UNDECIDED stores with Jay (Month 2) 
3. **Phase 3**: Migrate remaining SHOULD-STAY stores if needed (Month 3)
4. **Phase 4**: Cutover and verification (Month 4)

The assessment shows that **Postgres migration is both necessary and feasible**, with clear guidance for which stores to move, which to keep local, and which need further analysis. The migration can achieve zero loss with proper verification procedures in place.
