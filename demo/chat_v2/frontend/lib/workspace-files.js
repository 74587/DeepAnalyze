function normalizeWorkspacePath(path) {
  return String(path || "")
    .replace(/\\/g, "/")
    .replace(/^\/+/, "")
    .trim();
}

function isGeneratedWorkspaceFile(file) {
  if (!file) return false;
  if (file.is_generated === true) return true;
  const path = normalizeWorkspacePath(file.path);
  return path === "generated" || path.startsWith("generated/");
}

function countWorkspaceFiles(files) {
  const list = Array.isArray(files) ? files : [];
  const generated = list.filter(isGeneratedWorkspaceFile).length;
  return {
    uploaded: list.length - generated,
    generated,
    all: list.length,
  };
}

function filterWorkspaceFiles(files, view, query = "") {
  const normalizedQuery = String(query || "").trim().toLowerCase();
  return (Array.isArray(files) ? files : [])
    .filter((file) => {
      const generated = isGeneratedWorkspaceFile(file);
      if (view === "generated" && !generated) return false;
      if (view === "uploaded" && generated) return false;
      if (!normalizedQuery) return true;
      return [file.name, file.path].some((value) =>
        String(value || "").toLowerCase().includes(normalizedQuery)
      );
    })
    .sort((left, right) => {
      const leftGenerated = isGeneratedWorkspaceFile(left);
      const rightGenerated = isGeneratedWorkspaceFile(right);
      if (leftGenerated !== rightGenerated) return leftGenerated ? 1 : -1;
      return String(left.name || "").localeCompare(String(right.name || ""));
    });
}

module.exports = {
  countWorkspaceFiles,
  filterWorkspaceFiles,
  isGeneratedWorkspaceFile,
  normalizeWorkspacePath,
};
