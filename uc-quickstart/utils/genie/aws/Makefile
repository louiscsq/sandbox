.PHONY: help _guard-root _prepare-env _bootstrap _guard-workspace-target _guard-account-config _guard-data-access-config _guard-workspace-config setup init-env generate validate validate-generated promote plan sync-tags apply import migrate-state destroy clean clean-all migrate-root-to-env _apply-layer _plan-layer _destroy-layer

SHELL := /bin/bash
export DATABRICKS_USER_AGENT_EXTRA := genierails/0.1.0

ACCOUNT_ENV := account
DATA_ACCESS_SUBDIR := data_access
DEFAULT_ENV := dev
ENV ?= $(DEFAULT_ENV)
SOURCE_ENV ?= $(ENV)
DEST_ENV ?=
DEST_CATALOG ?=
ENV_ORIGIN := $(origin ENV)
MODULE_ROOT := $(shell cd "$(dir $(realpath $(lastword $(MAKEFILE_LIST))))" && pwd)
ENV_DIR := $(MODULE_ROOT)/envs/$(ENV)
SOURCE_ENV_DIR := $(MODULE_ROOT)/envs/$(SOURCE_ENV)
ACCOUNT_ENV_DIR := $(MODULE_ROOT)/envs/$(ACCOUNT_ENV)
ROOT_RUNNER := $(MODULE_ROOT)/scripts/terraform_layer.sh
TARGET_ENV_NAME = $(if $(TARGET_ENV),$(TARGET_ENV),$(ENV))
TARGET_ENV_DIR = $(MODULE_ROOT)/envs/$(TARGET_ENV_NAME)
TARGET_DATA_ACCESS_ENV_DIR = $(TARGET_ENV_DIR)/$(DATA_ACCESS_SUBDIR)

help: ## Show this help
	@awk 'BEGIN {FS = ":.*## "}; /^[a-z_-]+:.*## / {printf "  \033[36m%-22s\033[0m %s\n", $$1, $$2}' "$(lastword $(MAKEFILE_LIST))"
	@echo ""
	@echo "Environment selection:"
	@echo "  Use ENV=<workspace> for a workspace environment (default: $(DEFAULT_ENV))."
	@echo "  Reserved names:"
	@echo "    ENV=$(ACCOUNT_ENV)  (shared account layer)"
	@echo "    ENV=$(DATA_ACCESS_SUBDIR)  (reserved governance subdirectory name)"
	@echo "  Examples: make setup ; make apply ENV=prod ; make destroy ENV=$(ACCOUNT_ENV)"

_guard-root:
	@if [ "$(ENV_ORIGIN)" = "default" ] && [ ! -d "$(ENV_DIR)" ] && { \
		[ -f "$(MODULE_ROOT)/auth.auto.tfvars" ] || \
		[ -f "$(MODULE_ROOT)/env.auto.tfvars" ] || \
		[ -f "$(MODULE_ROOT)/abac.auto.tfvars" ] || \
		[ -f "$(MODULE_ROOT)/masking_functions.sql" ] || \
		[ -f "$(MODULE_ROOT)/.genie_space_id" ] || \
		[ -d "$(MODULE_ROOT)/.terraform" ] || \
		[ -f "$(MODULE_ROOT)/.terraform.lock.hcl" ] || \
		ls "$(MODULE_ROOT)"/terraform.tfstate* >/dev/null 2>&1 || \
		[ -f "$(MODULE_ROOT)/generated/abac.auto.tfvars" ] || \
		[ -f "$(MODULE_ROOT)/generated/masking_functions.sql" ] || \
		[ -f "$(MODULE_ROOT)/generated/generated_response.md" ] || \
		[ -f "$(MODULE_ROOT)/ddl/_fetched.sql" ]; \
	}; then \
		echo "Found existing working files in the project root."; \
		echo "Run 'make migrate-root-to-env ENV=$(DEFAULT_ENV)' first, or set ENV=<name> to create a new environment."; \
		exit 1; \
	fi

_prepare-env:
	@envs="$(ENV)"; \
	if [ "$(ENV)" != "$(ACCOUNT_ENV)" ] && [ "$(ENV)" != "$(DATA_ACCESS_SUBDIR)" ]; then \
		envs="$(ACCOUNT_ENV) $(ENV)"; \
	fi; \
	for env_name in $$envs; do \
		env_dir="$(MODULE_ROOT)/envs/$$env_name"; \
		mkdir -p "$$env_dir"; \
		if [ "$$env_name" = "$(ACCOUNT_ENV)" ]; then \
			rm -rf "$$env_dir/ddl" "$$env_dir/generated" "$$env_dir/$(DATA_ACCESS_SUBDIR)"; \
		else \
			mkdir -p "$$env_dir/ddl" "$$env_dir/generated"; \
			gov_dir="$$env_dir/$(DATA_ACCESS_SUBDIR)"; \
			mkdir -p "$$gov_dir"; \
			if [ ! -e "$$gov_dir/auth.auto.tfvars" ]; then ln -sfn ../auth.auto.tfvars "$$gov_dir/auth.auto.tfvars"; fi; \
			if [ ! -e "$$gov_dir/env.auto.tfvars" ]; then ln -sfn ../env.auto.tfvars "$$gov_dir/env.auto.tfvars"; fi; \
		fi; \
		rm -f "$$env_dir"/*.tf; \
		rm -f "$$env_dir"/*.py "$$env_dir"/ABAC_PROMPT.md; \
		rm -rf "$$env_dir/scripts"; \
		if [ ! -e "$$env_dir/auth.auto.tfvars" ]; then \
			if [ "$(ENV)" != "$(ACCOUNT_ENV)" ] && [ "$$env_name" = "$(ACCOUNT_ENV)" ]; then \
				ln -sfn "../$(ENV)/auth.auto.tfvars" "$$env_dir/auth.auto.tfvars"; \
			else \
				cp "$(MODULE_ROOT)/auth.auto.tfvars.example" "$$env_dir/auth.auto.tfvars"; \
			fi; \
		fi; \
		if [ ! -e "$$env_dir/env.auto.tfvars" ]; then \
			cp "$(MODULE_ROOT)/env.auto.tfvars.example" "$$env_dir/env.auto.tfvars"; \
			if [ "$$env_name" = "$(ACCOUNT_ENV)" ]; then \
				printf "\n# Account layer owns group creation.\nmanage_groups = true\n" >> "$$env_dir/env.auto.tfvars"; \
			fi; \
		fi; \
	done

_bootstrap:
	@$(MAKE) --no-print-directory _guard-root ENV="$(ENV)" ENV_ORIGIN="$(ENV_ORIGIN)"
	@$(MAKE) --no-print-directory _prepare-env ENV="$(ENV)" ENV_ORIGIN="$(ENV_ORIGIN)"

_guard-workspace-target:
	@if [ "$(ENV)" = "$(ACCOUNT_ENV)" ] || [ "$(ENV)" = "$(DATA_ACCESS_SUBDIR)" ]; then \
		echo "This command is workspace-driven. Use ENV=<workspace> instead of ENV=$(ENV)."; \
		exit 1; \
	fi

_guard-account-config:
	@cd "$(ACCOUNT_ENV_DIR)" && if [ -f abac.auto.tfvars ]; then \
		python3 -c 'import sys,hcl2; cfg=hcl2.load(open("abac.auto.tfvars")); bad=[name for name in ("tag_assignments","fgac_policies","genie_space_title","genie_space_description","genie_sample_questions","genie_instructions","genie_benchmarks","genie_sql_filters","genie_sql_expressions","genie_sql_measures","genie_join_specs") if cfg.get(name)]; bad and (print("Account config still contains non-account sections: " + ", ".join(bad)), sys.exit(1))'; \
	fi

_guard-data-access-config:
	@cd "$(TARGET_DATA_ACCESS_ENV_DIR)" && if [ -f abac.auto.tfvars ]; then \
		python3 -c 'import sys,hcl2; cfg=hcl2.load(open("abac.auto.tfvars")); bad=[name for name in ("group_members","tag_policies","genie_space_title","genie_space_description","genie_sample_questions","genie_instructions","genie_benchmarks","genie_sql_filters","genie_sql_expressions","genie_sql_measures","genie_join_specs") if cfg.get(name)]; bad and (print("Data-access config still contains non-data-access sections (tag_policies now belong in envs/account): " + ", ".join(bad)), sys.exit(1))'; \
	fi

_guard-workspace-config:
	@cd "$(ENV_DIR)" && if [ -f env.auto.tfvars ]; then \
		python3 -c 'import sys,hcl2; cfg=hcl2.load(open("env.auto.tfvars")); ok = cfg.get("manage_groups", False) is False; ok or print("Workspace env.auto.tfvars must not set manage_groups = true. Manage groups in envs/account instead."); sys.exit(0 if ok else 1)'; \
	fi
	@cd "$(ENV_DIR)" && if [ -f abac.auto.tfvars ]; then \
		python3 -c 'import sys,hcl2; cfg=hcl2.load(open("abac.auto.tfvars")); bad=[name for name in ("group_members","tag_policies","tag_assignments","fgac_policies") if cfg.get(name)]; bad and (print("Workspace config still contains shared sections: " + ", ".join(bad)), print("Re-run '\''make promote$(if $(filter $(ENV),$(DEFAULT_ENV)),, ENV=$(ENV))'\'' to resplit the generated config."), sys.exit(1))'; \
	fi

setup: _bootstrap ## Prepare the selected environment(s) and show next steps
	@echo "=== Setup ($(ENV)) ==="
	@if [ "$(ENV)" = "$(ACCOUNT_ENV)" ]; then \
		echo "Shared account environment ready:     $(ACCOUNT_ENV_DIR)"; \
		echo ""; \
		echo "Next steps:"; \
		echo "  1. Edit $(ACCOUNT_ENV_DIR)/auth.auto.tfvars"; \
		echo "  2. Review $(ACCOUNT_ENV_DIR)/env.auto.tfvars"; \
		echo "  3. Run: make apply ENV=$(ACCOUNT_ENV)"; \
	else \
		echo "Shared account environment ready:     $(ACCOUNT_ENV_DIR)"; \
		echo "Environment governance ready:         $(ENV_DIR)/$(DATA_ACCESS_SUBDIR)"; \
		echo "Workspace environment ready:          $(ENV_DIR)"; \
		echo ""; \
		echo "Next steps:"; \
		echo "  1. Edit $(ENV_DIR)/auth.auto.tfvars"; \
		echo "  2. Edit $(ENV_DIR)/env.auto.tfvars"; \
		echo "  3. Run: make generate$(if $(filter $(ENV),$(DEFAULT_ENV)),, ENV=$(ENV))"; \
		echo "  4. Run: make apply$(if $(filter $(ENV),$(DEFAULT_ENV)),, ENV=$(ENV))"; \
	fi

init-env: _bootstrap ## Prepare env directories and default config files
	@echo "Environment bootstrap ready for $(ENV)."

generate: _bootstrap _guard-workspace-target ## Run generate_abac.py in the selected workspace environment
	@echo "=== Generate ABAC Config ($(ENV)) ==="
	@cd "$(ENV_DIR)" && python "$(MODULE_ROOT)/generate_abac.py" $(GENERATE_ARGS)

validate-generated: _bootstrap _guard-workspace-target ## Validate generated/ files in the selected workspace environment
	@echo "=== Validate (generated/) [$(ENV)] ==="
	@cd "$(ENV_DIR)" && if [ -f generated/masking_functions.sql ]; then \
		python "$(MODULE_ROOT)/validate_abac.py" generated/abac.auto.tfvars generated/masking_functions.sql; \
	else \
		python "$(MODULE_ROOT)/validate_abac.py" generated/abac.auto.tfvars; \
	fi

validate: _bootstrap ## Validate split config in the selected environment
	@echo "=== Validate ($(ENV)) ==="
	@if [ "$(ENV)" = "$(ACCOUNT_ENV)" ]; then \
		cd "$(ACCOUNT_ENV_DIR)" && if [ -f abac.auto.tfvars ]; then python "$(MODULE_ROOT)/validate_abac.py" abac.auto.tfvars; fi; \
	else \
		cd "$(ENV_DIR)/$(DATA_ACCESS_SUBDIR)" && if [ -f abac.auto.tfvars ]; then python "$(MODULE_ROOT)/validate_abac.py" abac.auto.tfvars masking_functions.sql; fi; \
		cd "$(ENV_DIR)" && python "$(MODULE_ROOT)/validate_abac.py" abac.auto.tfvars; \
	fi

promote: _bootstrap _guard-workspace-target ## Split generated/ into layers (same-env), or cross-env: make promote SOURCE_ENV=dev DEST_ENV=prod DEST_CATALOG=prod_catalog
	@if [ -n "$(DEST_ENV)" ]; then \
		if [ "$(DEST_ENV)" = "$(ACCOUNT_ENV)" ] || [ "$(DEST_ENV)" = "$(DATA_ACCESS_SUBDIR)" ]; then \
			echo "ERROR: DEST_ENV cannot be '$(ACCOUNT_ENV)' or '$(DATA_ACCESS_SUBDIR)'."; exit 1; \
		fi; \
		if [ -z "$(DEST_CATALOG)" ]; then \
			echo "ERROR: DEST_CATALOG is required for cross-env promotion."; \
			echo "  make promote SOURCE_ENV=$(ENV) DEST_ENV=$(DEST_ENV) DEST_CATALOG=<catalog_name>"; \
			exit 1; \
		fi; \
		if [ "$(SOURCE_ENV)" = "$(ACCOUNT_ENV)" ] || [ "$(SOURCE_ENV)" = "$(DATA_ACCESS_SUBDIR)" ]; then \
			echo "ERROR: SOURCE_ENV must be a workspace environment, not $(SOURCE_ENV)."; exit 1; \
		fi; \
		if [ ! -f "$(SOURCE_ENV_DIR)/generated/abac.auto.tfvars" ]; then \
			echo "ERROR: No $(SOURCE_ENV_DIR)/generated/abac.auto.tfvars found."; \
			echo "  Run 'make generate$(if $(filter $(SOURCE_ENV),$(DEFAULT_ENV)),, ENV=$(SOURCE_ENV))' first."; \
			exit 1; \
		fi; \
		echo "=== Cross-env promote: $(SOURCE_ENV) -> $(DEST_ENV) (catalog: $(DEST_CATALOG)) ==="; \
		$(MAKE) --no-print-directory _prepare-env ENV="$(DEST_ENV)"; \
		dest_env_dir="$(MODULE_ROOT)/envs/$(DEST_ENV)"; \
		src_catalog=$$(python3 -c "import hcl2; cfg=hcl2.load(open('$(SOURCE_ENV_DIR)/env.auto.tfvars')); print(cfg.get('uc_catalog',''))"); \
		tables_hcl=$$(python3 -c "import hcl2; cfg=hcl2.load(open('$(SOURCE_ENV_DIR)/env.auto.tfvars')); ts=cfg.get('uc_tables',[]); print('[' + ', '.join('\"' + t + '\"' for t in ts) + ']')"); \
		printf 'uc_catalog       = "%s"\nuc_tables        = %s\nsql_warehouse_id = ""\ngenie_space_id   = ""\n' "$(DEST_CATALOG)" "$$tables_hcl" > "$$dest_env_dir/env.auto.tfvars"; \
		echo "  Wrote $$dest_env_dir/env.auto.tfvars (catalog: $$src_catalog -> $(DEST_CATALOG))"; \
		mkdir -p "$$dest_env_dir/generated"; \
		python3 "$(MODULE_ROOT)/scripts/remap_generated_config.py" \
			"$(SOURCE_ENV_DIR)/generated/abac.auto.tfvars" \
			"$(SOURCE_ENV_DIR)/generated/masking_functions.sql" \
			"$$src_catalog" \
			"$(DEST_CATALOG)" \
			"$$dest_env_dir/generated/abac.auto.tfvars" \
			"$$dest_env_dir/generated/masking_functions.sql"; \
		cd "$$dest_env_dir" && python3 "$(MODULE_ROOT)/scripts/split_abac_config.py" generated/abac.auto.tfvars ../$(ACCOUNT_ENV)/abac.auto.tfvars $(DATA_ACCESS_SUBDIR)/abac.auto.tfvars abac.auto.tfvars; \
		cp "$$dest_env_dir/generated/masking_functions.sql" "$$dest_env_dir/$(DATA_ACCESS_SUBDIR)/masking_functions.sql"; \
		cd "$(ACCOUNT_ENV_DIR)" && if [ -f abac.auto.tfvars ]; then python "$(MODULE_ROOT)/validate_abac.py" abac.auto.tfvars; fi; \
		cd "$$dest_env_dir/$(DATA_ACCESS_SUBDIR)" && if [ -f abac.auto.tfvars ]; then python "$(MODULE_ROOT)/validate_abac.py" abac.auto.tfvars masking_functions.sql; fi; \
		cd "$$dest_env_dir" && python "$(MODULE_ROOT)/validate_abac.py" abac.auto.tfvars; \
		echo ""; \
		echo "=== Promote complete: $(SOURCE_ENV) -> $(DEST_ENV) ==="; \
		echo "  Next: edit $$dest_env_dir/auth.auto.tfvars  ($(DEST_ENV) workspace credentials)"; \
		echo "  Then: make apply ENV=$(DEST_ENV)"; \
	else \
		if [ "$(SOURCE_ENV)" = "$(ACCOUNT_ENV)" ] || [ "$(SOURCE_ENV)" = "$(DATA_ACCESS_SUBDIR)" ]; then \
			echo "ERROR: SOURCE_ENV must be a workspace environment, not $(SOURCE_ENV)."; exit 1; \
		fi; \
		if [ ! -f "$(ENV_DIR)/generated/abac.auto.tfvars" ]; then \
			echo "No $(ENV_DIR)/generated/abac.auto.tfvars found. Run 'make generate$(if $(filter $(ENV),$(DEFAULT_ENV)),, ENV=$(ENV))' first."; exit 1; \
		fi; \
		echo "=== Split generated/ to account + data_access + workspace ($(ENV)) ==="; \
		if [ -f "$(ENV_DIR)/generated/masking_functions.sql" ]; then \
			cd "$(ENV_DIR)" && python "$(MODULE_ROOT)/validate_abac.py" generated/abac.auto.tfvars generated/masking_functions.sql; \
		else \
			cd "$(ENV_DIR)" && python "$(MODULE_ROOT)/validate_abac.py" generated/abac.auto.tfvars; \
		fi; \
		cd "$(ENV_DIR)" && python3 "$(MODULE_ROOT)/scripts/split_abac_config.py" generated/abac.auto.tfvars ../$(ACCOUNT_ENV)/abac.auto.tfvars $(DATA_ACCESS_SUBDIR)/abac.auto.tfvars abac.auto.tfvars; \
		if [ -f "$(ENV_DIR)/generated/masking_functions.sql" ]; then \
			cp "$(ENV_DIR)/generated/masking_functions.sql" "$(ENV_DIR)/$(DATA_ACCESS_SUBDIR)/masking_functions.sql"; \
		fi; \
		cd "$(ACCOUNT_ENV_DIR)" && if [ -f abac.auto.tfvars ]; then python "$(MODULE_ROOT)/validate_abac.py" abac.auto.tfvars; fi; \
		cd "$(ENV_DIR)/$(DATA_ACCESS_SUBDIR)" && if [ -f abac.auto.tfvars ]; then python "$(MODULE_ROOT)/validate_abac.py" abac.auto.tfvars masking_functions.sql; fi; \
		cd "$(ENV_DIR)" && python "$(MODULE_ROOT)/validate_abac.py" abac.auto.tfvars; \
	fi

_plan-layer:
	@layer="$(LAYER)"; target_env="$(TARGET_ENV)"; \
	echo "=== Terraform Plan ($$layer:$$target_env) ==="; \
	"$(ROOT_RUNNER)" "$$layer" "$$target_env" plan

plan: _bootstrap ## Run terraform plan for the selected layer or workspace env
	@set -e; if [ "$(ENV)" = "$(ACCOUNT_ENV)" ]; then \
		$(MAKE) --no-print-directory _guard-account-config; \
		$(MAKE) --no-print-directory _plan-layer LAYER=account TARGET_ENV=$(ACCOUNT_ENV); \
	else \
		$(MAKE) --no-print-directory ENV="$(ENV)" _guard-workspace-config; \
		$(MAKE) --no-print-directory ENV="$(ENV)" TARGET_ENV="$(ENV)" _guard-data-access-config; \
		$(MAKE) --no-print-directory _plan-layer LAYER=data_access TARGET_ENV=$(ENV); \
		$(MAKE) --no-print-directory _plan-layer LAYER=workspace TARGET_ENV=$(ENV); \
	fi

sync-tags: _bootstrap ## Sync tag policy values in the shared account layer
	@$(MAKE) --no-print-directory _guard-account-config
	@echo "=== Sync Tag Policies (account) ==="
	@cd "$(ACCOUNT_ENV_DIR)" && python3 "$(MODULE_ROOT)/scripts/sync_tag_policies.py"

_apply-layer:
	@set -e; layer="$(LAYER)"; target_env="$(TARGET_ENV)"; \
	case "$$layer" in \
		account) env_dir="$(ACCOUNT_ENV_DIR)" ;; \
		data_access) env_dir="$(MODULE_ROOT)/envs/$$target_env/$(DATA_ACCESS_SUBDIR)" ;; \
		workspace) env_dir="$(MODULE_ROOT)/envs/$$target_env" ;; \
		*) echo "Unknown layer $$layer"; exit 1 ;; \
	esac; \
	if [ ! -f "$$env_dir/abac.auto.tfvars" ]; then \
		echo "=== Skipping terraform apply ($$layer:$$target_env): no $$env_dir/abac.auto.tfvars ==="; \
		exit 0; \
	fi; \
	if [ "$$layer" = "account" ]; then \
		$(MAKE) --no-print-directory sync-tags; \
	fi; \
	files="$$env_dir/auth.auto.tfvars $$env_dir/env.auto.tfvars $$env_dir/abac.auto.tfvars"; \
	if [ -f "$$env_dir/masking_functions.sql" ]; then files="$$files $$env_dir/masking_functions.sql"; fi; \
	fingerprint_file="$$env_dir/.$$layer.apply.sha"; \
	current_fingerprint="$$(for file in $$files; do [ -f "$$file" ] && shasum "$$file"; done | shasum | awk '{print $$1}')"; \
	if [ -f "$$fingerprint_file" ] && [ "$$(cat "$$fingerprint_file")" = "$$current_fingerprint" ]; then \
		echo "=== Skipping terraform apply ($$layer:$$target_env): inputs unchanged ==="; \
		exit 0; \
	fi; \
	echo "=== Terraform Apply ($$layer:$$target_env) ==="; \
	"$(ROOT_RUNNER)" "$$layer" "$$target_env" apply -parallelism=1 -auto-approve; \
	printf "%s\n" "$$current_fingerprint" > "$$fingerprint_file"

apply: _bootstrap ## Apply the selected layer, or account -> data_access -> workspace for ENV=<workspace>
	@set -e; if [ "$(ENV)" = "$(ACCOUNT_ENV)" ]; then \
		$(MAKE) --no-print-directory _guard-account-config; \
		$(MAKE) --no-print-directory _apply-layer LAYER=account TARGET_ENV=$(ACCOUNT_ENV); \
	else \
		$(MAKE) --no-print-directory ENV="$(ENV)" _guard-workspace-config; \
		if [ -f "$(ENV_DIR)/generated/abac.auto.tfvars" ]; then \
			$(MAKE) --no-print-directory ENV="$(ENV)" promote; \
		else \
			echo "=== Skipping promote (no $(ENV_DIR)/generated/abac.auto.tfvars) ==="; \
		fi; \
		$(MAKE) --no-print-directory _guard-account-config; \
		$(MAKE) --no-print-directory TARGET_ENV="$(ENV)" _guard-data-access-config; \
		$(MAKE) --no-print-directory _apply-layer LAYER=account TARGET_ENV=$(ACCOUNT_ENV); \
		$(MAKE) --no-print-directory _apply-layer LAYER=data_access TARGET_ENV=$(ENV); \
		$(MAKE) --no-print-directory _apply-layer LAYER=workspace TARGET_ENV=$(ENV); \
	fi

import: _bootstrap ## Import existing resources into the selected layer state
	@echo "=== Import Existing Resources ($(ENV)) ==="
	@if [ "$(ENV)" = "$(ACCOUNT_ENV)" ]; then \
		cd "$(ACCOUNT_ENV_DIR)" && "$(MODULE_ROOT)/scripts/import_existing.sh"; \
	else \
		cd "$(ENV_DIR)/$(DATA_ACCESS_SUBDIR)" && "$(MODULE_ROOT)/scripts/import_existing.sh"; \
		cd "$(ENV_DIR)" && "$(MODULE_ROOT)/scripts/import_existing.sh"; \
	fi

migrate-state: _bootstrap ## Migrate legacy state into account/data_access/workspace ownership
	@echo "=== Migrate Terraform State ($(ENV)) ==="
	@if [ "$(ENV)" = "$(ACCOUNT_ENV)" ]; then \
		if [ ! -f "$(ACCOUNT_ENV_DIR)/terraform.tfstate" ]; then echo "No Terraform state found in $(ACCOUNT_ENV_DIR)."; exit 0; fi; \
		"$(ROOT_RUNNER)" account $(ACCOUNT_ENV) state-list 2>/dev/null | python3 -c 'import re,sys; [print(line.strip()) for line in sys.stdin if re.match(r"^databricks_group\\.groups\\[", line.strip())]' | while read addr; do suffix="$${addr#databricks_group.groups}"; "$(ROOT_RUNNER)" account $(ACCOUNT_ENV) state-mv "$$addr" "module.account.databricks_group.groups$$suffix"; done; \
		"$(ROOT_RUNNER)" account $(ACCOUNT_ENV) state-list 2>/dev/null | python3 -c 'import re,sys; [print(line.strip()) for line in sys.stdin if re.match(r"^databricks_group_member\\.members\\[", line.strip())]' | while read addr; do suffix="$${addr#databricks_group_member.members}"; "$(ROOT_RUNNER)" account $(ACCOUNT_ENV) state-mv "$$addr" "module.account.databricks_group_member.members$$suffix"; done; \
	else \
		$(MAKE) --no-print-directory migrate-state ENV=$(ACCOUNT_ENV); \
		legacy_dir="$(MODULE_ROOT)/envs/$(DATA_ACCESS_SUBDIR)"; target_gov_dir="$(ENV_DIR)/$(DATA_ACCESS_SUBDIR)"; \
		if [ -d "$$legacy_dir" ] && [ ! -f "$$target_gov_dir/terraform.tfstate" ]; then \
			mkdir -p "$$target_gov_dir"; \
			for name in abac.auto.tfvars masking_functions.sql terraform.tfstate terraform.tfstate.backup .terraform.lock.hcl .data_access.apply.sha; do \
				if [ -e "$$legacy_dir/$$name" ] && [ ! -e "$$target_gov_dir/$$name" ]; then mv "$$legacy_dir/$$name" "$$target_gov_dir/$$name"; fi; \
			done; \
			if [ -d "$$legacy_dir/.terraform" ] && [ ! -d "$$target_gov_dir/.terraform" ]; then mv "$$legacy_dir/.terraform" "$$target_gov_dir/.terraform"; fi; \
			echo "Migrated legacy shared data_access files into $$target_gov_dir"; \
		fi; \
		if [ -f "$(ENV_DIR)/$(DATA_ACCESS_SUBDIR)/terraform.tfstate" ]; then \
			"$(ROOT_RUNNER)" data_access $(ENV) state-list 2>/dev/null | python3 -c 'import re,sys; [print(line.strip()) for line in sys.stdin if re.match(r"^module\.data_access\.databricks_tag_policy\.policies\\[", line.strip())]' | while read addr; do \
				key=$$(printf "%s" "$$addr" | python3 -c 'import sys; text=sys.stdin.read().strip(); start=text.find("[\""); end=text.rfind("\"]"); print(text[start+2:end] if start != -1 and end != -1 else "")'); \
				[ -n "$$key" ] || continue; \
				"$(ROOT_RUNNER)" data_access $(ENV) state-rm "$$addr" >/dev/null || true; \
				"$(ROOT_RUNNER)" account $(ACCOUNT_ENV) import "module.account.databricks_tag_policy.policies[\"$$key\"]" "$$key" >/dev/null 2>&1 || true; \
			done; \
		fi; \
		if [ -f "$(ENV_DIR)/terraform.tfstate" ]; then \
			for pair in \
				"data.databricks_group.existing module.workspace.data.databricks_group.existing" \
				"databricks_mws_permission_assignment.group_assignments module.workspace.databricks_mws_permission_assignment.group_assignments" \
				"databricks_entitlements.group_entitlements module.workspace.databricks_entitlements.group_entitlements" \
				"databricks_sql_endpoint.warehouse module.workspace.databricks_sql_endpoint.warehouse" \
				"null_resource.genie_space_acls module.workspace.null_resource.genie_space_acls" \
				"null_resource.genie_space_create module.workspace.null_resource.genie_space_create" \
				"null_resource.genie_space_config module.workspace.null_resource.genie_space_config" \
				"null_resource.genie_space_acls_created module.workspace.null_resource.genie_space_acls_created"; do \
				old=$${pair% *}; new=$${pair#* }; \
				"$(ROOT_RUNNER)" workspace $(ENV) state-list 2>/dev/null | python3 -c 'import re,sys; pattern=sys.argv[1]; [print(line.strip()) for line in sys.stdin if re.match(pattern, line.strip())]' "^$${old}(\\[|$$)" | while read addr; do suffix="$${addr#$$old}"; "$(ROOT_RUNNER)" workspace $(ENV) state-mv "$$addr" "$$new$$suffix"; done; \
			done; \
			"$(ROOT_RUNNER)" workspace $(ENV) state-list 2>/dev/null | python3 -c 'import re,sys; pattern=r"^(databricks_tag_policy\\.policies|databricks_entity_tag_assignment\\.assignments|time_sleep\\.wait_for_tag_propagation|databricks_grant\\.(terraform_sp_manage_catalog|catalog_access)|null_resource\\.deploy_masking_functions|databricks_policy_info\\.policies|module\\.workspace\\.(databricks_tag_policy\\.policies|databricks_entity_tag_assignment\\.assignments|time_sleep\\.wait_for_tag_propagation|databricks_grant\\.(terraform_sp_manage_catalog|catalog_access)|null_resource\\.deploy_masking_functions|databricks_policy_info\\.policies))"; [print(line.strip()) for line in sys.stdin if re.match(pattern, line.strip())]' | while read addr; do "$(ROOT_RUNNER)" workspace $(ENV) state-rm "$$addr" >/dev/null || true; done; \
		fi; \
		cd "$(ENV_DIR)/$(DATA_ACCESS_SUBDIR)" && if [ -f abac.auto.tfvars ]; then "$(MODULE_ROOT)/scripts/import_existing.sh"; fi; \
	fi

_destroy-layer:
	@layer="$(LAYER)"; target_env="$(TARGET_ENV)"; \
	echo "=== Terraform Destroy ($$layer:$$target_env) ==="; \
	"$(ROOT_RUNNER)" "$$layer" "$$target_env" destroy -auto-approve

destroy: _bootstrap ## Destroy the selected layer or workspace environment
	@if [ "$(ENV)" = "$(ACCOUNT_ENV)" ]; then \
		$(MAKE) --no-print-directory _destroy-layer LAYER=account TARGET_ENV=$(ACCOUNT_ENV); \
	else \
		$(MAKE) --no-print-directory _destroy-layer LAYER=workspace TARGET_ENV=$(ENV); \
		$(MAKE) --no-print-directory _destroy-layer LAYER=data_access TARGET_ENV=$(ENV); \
	fi

clean: ## Remove generated files and Terraform state for the selected environment
	@if [ ! -d "$(ENV_DIR)" ]; then \
		echo "Environment '$(ENV)' not initialized: $(ENV_DIR)"; \
		exit 0; \
	fi
	@echo "=== Clean ($(ENV)) ==="
	@rm -rf "$(ENV_DIR)/generated/abac.auto.tfvars" "$(ENV_DIR)/generated/masking_functions.sql" "$(ENV_DIR)/generated/generated_response.md"
	@rm -rf "$(ENV_DIR)/.terraform" "$(ENV_DIR)"/*.tfstate "$(ENV_DIR)"/*.tfstate.backup "$(ENV_DIR)"/.terraform.lock.hcl "$(ENV_DIR)"/.*.apply.sha
	@rm -rf "$(ENV_DIR)/$(DATA_ACCESS_SUBDIR)/.terraform" "$(ENV_DIR)/$(DATA_ACCESS_SUBDIR)"/*.tfstate "$(ENV_DIR)/$(DATA_ACCESS_SUBDIR)"/*.tfstate.backup "$(ENV_DIR)/$(DATA_ACCESS_SUBDIR)"/.terraform.lock.hcl "$(ENV_DIR)/$(DATA_ACCESS_SUBDIR)"/.*.apply.sha
	@echo "Cleaned generated files and Terraform state in $(ENV_DIR)."
	@echo "NOTE: auth.auto.tfvars, env.auto.tfvars, abac.auto.tfvars, $(DATA_ACCESS_SUBDIR)/abac.auto.tfvars, $(DATA_ACCESS_SUBDIR)/masking_functions.sql, and .genie_space_id were NOT removed."

clean-all: ## Remove all env workspaces under envs/
	@echo "=== Clean All Environments ==="
	@rm -rf "$(MODULE_ROOT)/envs"
	@echo "Removed $(MODULE_ROOT)/envs"

migrate-root-to-env: _prepare-env ## Move existing root working files into envs/<ENV>
	@echo "=== Migrate Root Workspace to $(ENV) ==="
	@if [ -f "$(ENV_DIR)/auth.auto.tfvars" ] || \
		[ -f "$(ENV_DIR)/env.auto.tfvars" ] || \
		[ -f "$(ENV_DIR)/abac.auto.tfvars" ] || \
		[ -f "$(ENV_DIR)/generated/abac.auto.tfvars" ] || \
		[ -f "$(ENV_DIR)/generated/masking_functions.sql" ] || \
		[ -f "$(ENV_DIR)/$(DATA_ACCESS_SUBDIR)/abac.auto.tfvars" ] || \
		[ -f "$(ENV_DIR)/$(DATA_ACCESS_SUBDIR)/masking_functions.sql" ] || \
		[ -f "$(ENV_DIR)/.genie_space_id" ] || \
		[ -f "$(ENV_DIR)/.terraform.lock.hcl" ] || \
		[ -d "$(ENV_DIR)/.terraform" ] || \
		[ -n "$$(ls -A "$(ENV_DIR)/ddl" 2>/dev/null)" ] || \
		[ -n "$$(ls -A "$(ENV_DIR)/generated" 2>/dev/null)" ] || \
		ls "$(ENV_DIR)"/terraform.tfstate* >/dev/null 2>&1; then \
		echo "Target environment already contains working files: $(ENV_DIR)"; \
		echo "Choose a new ENV or clean the target environment before migrating."; \
		exit 1; \
	fi
	@found=0; \
	for file in auth.auto.tfvars env.auto.tfvars .genie_space_id .terraform.lock.hcl; do \
		if [ -e "$(MODULE_ROOT)/$$file" ]; then \
			mv "$(MODULE_ROOT)/$$file" "$(ENV_DIR)/$$file"; \
			echo "Moved $$file"; \
			found=1; \
		fi; \
	done; \
	if [ -f "$(MODULE_ROOT)/abac.auto.tfvars" ]; then \
		mv "$(MODULE_ROOT)/abac.auto.tfvars" "$(ENV_DIR)/generated/abac.auto.tfvars"; \
		echo "Moved abac.auto.tfvars -> generated/abac.auto.tfvars"; \
		found=1; \
	fi; \
	if [ -f "$(MODULE_ROOT)/masking_functions.sql" ]; then \
		mv "$(MODULE_ROOT)/masking_functions.sql" "$(ENV_DIR)/generated/masking_functions.sql"; \
		echo "Moved masking_functions.sql -> generated/masking_functions.sql"; \
		found=1; \
	fi; \
	if [ -d "$(MODULE_ROOT)/ddl" ]; then \
		if [ -n "$$(ls -A "$(MODULE_ROOT)/ddl" 2>/dev/null)" ]; then \
			cp -R "$(MODULE_ROOT)/ddl/." "$(ENV_DIR)/ddl/"; \
			echo "Copied ddl/"; \
			found=1; \
		fi; \
		rm -rf "$(MODULE_ROOT)/ddl"; \
	fi; \
	if [ -d "$(MODULE_ROOT)/generated" ]; then \
		if [ -n "$$(ls -A "$(MODULE_ROOT)/generated" 2>/dev/null)" ]; then \
			cp -R "$(MODULE_ROOT)/generated/." "$(ENV_DIR)/generated/"; \
			echo "Copied generated/"; \
			found=1; \
		fi; \
		rm -rf "$(MODULE_ROOT)/generated"; \
	fi; \
	if [ -d "$(MODULE_ROOT)/.terraform" ]; then \
		mv "$(MODULE_ROOT)/.terraform" "$(ENV_DIR)/.terraform"; \
		echo "Moved .terraform/"; \
		found=1; \
	fi; \
	for path in "$(MODULE_ROOT)"/terraform.tfstate*; do \
		[ -e "$$path" ] || continue; \
		mv "$$path" "$(ENV_DIR)/"; \
		echo "Moved $$(basename "$$path")"; \
		found=1; \
	done; \
	if [ ! -f "$(ENV_DIR)/auth.auto.tfvars" ]; then \
		cp "$(MODULE_ROOT)/auth.auto.tfvars.example" "$(ENV_DIR)/auth.auto.tfvars"; \
	fi; \
	if [ ! -f "$(ENV_DIR)/env.auto.tfvars" ]; then \
		cp "$(MODULE_ROOT)/env.auto.tfvars.example" "$(ENV_DIR)/env.auto.tfvars"; \
	fi; \
	if [ "$$found" -eq 0 ]; then \
		echo "No root working files found to migrate."; \
	else \
		echo "Root workspace migrated to $(ENV_DIR)."; \
	fi
