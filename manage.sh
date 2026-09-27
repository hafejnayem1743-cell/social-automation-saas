#!/data/data/com.termux/files/usr/bin/bash
set -e
echo "=== NBSA SETUP ==="
echo "Python: $(python --version)"
echo "Node: $(node --version)"
echo "npm: $(npm --version)"
echo "Creating project folders..."
mkdir -p backend/app/{api,models,schemas,services,connectors,scheduler,workers,analytics,tracking,security}
mkdir -p backend/tests backend/migrations
mkdir -p frontend/src/{components,pages,hooks,services,lib,types}
mkdir -p workers/{scheduler,queue,workflows} scripts docs .github/workflows
echo "Folders created successfully."
echo "=== NBSA FOUNDATION READY ==="
