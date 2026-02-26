list:
	make -qp | awk -F: '/^[a-zA-Z0-9][a-zA-Z0-9_.-]*:/ {print $$1}' | grep -v 'Makefile'

engine-arm:
	DOCKER_BUILDKIT=1 docker buildx build --platform linux/arm64 --progress=plain --file engine.arm64.Dockerfile  -t seclens-engine-arm:0.2 .

engine-amd:
	DOCKER_BUILDKIT=1 docker buildx build --platform linux/amd64 --progress=plain --file engine.amd64.Dockerfile  -t seclens-engine-amd:0.2 .

security-sdk-subtree-setup:
	../scripts/update-security-sdk-subtree.sh --setup-only

security-sdk-subtree-update:
	@if [ -z "$(REF)" ]; then \
		echo "Usage: make security-sdk-subtree-update REF=<tag-or-branch>"; \
		exit 1; \
	fi
	../scripts/update-security-sdk-subtree.sh --ref $(REF)

security-sdk-subtree-dry-run:
	@if [ -z "$(REF)" ]; then \
		echo "Usage: make security-sdk-subtree-dry-run REF=<tag-or-branch>"; \
		exit 1; \
	fi
	../scripts/update-security-sdk-subtree.sh --ref $(REF) --dry-run

openclaw-subtree-setup:
	../scripts/update-openclaw-subtree.sh --setup-only

openclaw-subtree-update:
	@if [ -z "$(REF)" ]; then \
		echo "Usage: make openclaw-subtree-update REF=<tag-or-branch>"; \
		exit 1; \
	fi
	../scripts/update-openclaw-subtree.sh --ref $(REF)

openclaw-subtree-dry-run:
	@if [ -z "$(REF)" ]; then \
		echo "Usage: make openclaw-subtree-dry-run REF=<tag-or-branch>"; \
		exit 1; \
	fi
	../scripts/update-openclaw-subtree.sh --ref $(REF) --dry-run
