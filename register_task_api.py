filepath = "apps/api/cloudsite/main.py"

with open(filepath, "r") as f:
    content = f.read()

# Add import after parser_candidates import
old_import = "from .routers.admin.parser_candidates import router as admin_parser_candidates_router"
new_import = old_import + "\nfrom .platform.tasks.api import router as admin_tasks_router"
content = content.replace(old_import, new_import)

# Add include_router after parser_candidates include
old_include = "app.include_router(admin_parser_candidates_router)\n"
new_include = old_include + "app.include_router(admin_tasks_router)\n"
content = content.replace(old_include, new_include)

with open(filepath, "w") as f:
    f.write(content)

print("Task API router registered in main.py")