"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Check, CheckCircle2, ChevronRight, Database, Eye, EyeOff, Folder, FolderPlus, FolderSearch, Link2, Pencil, Power, RefreshCw, Save, Server, Trash2, X } from "lucide-react";
import { FormEvent, useEffect, useState } from "react";
import { AdminShell } from "@/components/AdminShell";
import { api } from "@/lib/api";

type AListSettings = { base_url: string; username: string; enabled: boolean; remember_credentials: boolean; connection_status: string; last_test_status: string; last_test_message: string; last_test_at: string | null; has_password: boolean };
type Mapping = { id: number; content_type: string; display_name: string; alist_path: string; enabled: boolean; sort_order: number };
type SystemSettings = { automatic_sync: boolean; sync_interval_minutes: number; sync_on_startup: boolean; version: string; database: string; timezone: string; resources: number; folders: number; operation_logs: number };
type DirectoryItem = { name: string; path: string; modified: string | null };
type DirectoryResponse = { path: string; parent_path: string; items: DirectoryItem[] };

const contentTypes = [
  ["software", "软件"], ["image", "图片"], ["video", "视频"], ["document", "文档"], ["file", "普通文件"],
] as const;

function inferContentType(name: string) {
  const value = name.toLowerCase();
  if (/软件|应用|程序|apps?|software/.test(value)) return "software";
  if (/图片|照片|相册|images?|photos?/.test(value)) return "image";
  if (/视频|影视|电影|videos?|movies?/.test(value)) return "video";
  if (/文档|资料|书籍|documents?|docs?|books?/.test(value)) return "document";
  return "file";
}

function pathName(path: string) {
  return path.split("/").filter(Boolean).at(-1) || "根目录";
}

export default function SystemPage() {
  const queryClient = useQueryClient();
  const alist = useQuery({ queryKey: ["alist"], queryFn: () => api<AListSettings>("/api/admin/alist") });
  const mappings = useQuery({ queryKey: ["mappings"], queryFn: () => api<{ items: Mapping[] }>("/api/admin/root-mappings") });
  const system = useQuery({ queryKey: ["system"], queryFn: () => api<SystemSettings>("/api/admin/system") });
  const [alistForm, setAlistForm] = useState({ base_url: "", username: "", password: "", remember_credentials: true });
  const [showPassword, setShowPassword] = useState(false);
  const [systemForm, setSystemForm] = useState({ automatic_sync: false, sync_interval_minutes: 360, sync_on_startup: false });
  const [mappingForm, setMappingForm] = useState({ content_type: "software", display_name: "", alist_path: "" });
  const [editingMappingId, setEditingMappingId] = useState<number | null>(null);
  const [pickerOpen, setPickerOpen] = useState(false);
  const [browserPath, setBrowserPath] = useState("/");
  const [selectedDirectory, setSelectedDirectory] = useState<DirectoryItem | null>(null);

  useEffect(() => { if (alist.data) setAlistForm((value) => ({ ...value, base_url: alist.data.base_url, username: alist.data.username, remember_credentials: alist.data.remember_credentials })); }, [alist.data]);
  useEffect(() => { if (system.data) setSystemForm({ automatic_sync: system.data.automatic_sync, sync_interval_minutes: system.data.sync_interval_minutes, sync_on_startup: system.data.sync_on_startup }); }, [system.data]);

  const rootDirectories = useQuery({
    queryKey: ["alist-directories", "/"],
    queryFn: () => api<DirectoryResponse>("/api/admin/alist/directories?path=%2F"),
    enabled: Boolean(alist.data?.enabled),
    retry: false,
  });
  const browserDirectories = useQuery({
    queryKey: ["alist-directories", browserPath],
    queryFn: () => api<DirectoryResponse>(`/api/admin/alist/directories?path=${encodeURIComponent(browserPath)}`),
    enabled: pickerOpen && Boolean(alist.data?.enabled),
    retry: false,
  });

  const saveAlist = useMutation({ mutationFn: () => api("/api/admin/alist", { method: "PUT", body: JSON.stringify(alistForm) }), onSuccess: () => { setAlistForm((value) => ({ ...value, password: "" })); queryClient.invalidateQueries({ queryKey: ["alist"] }); queryClient.invalidateQueries({ queryKey: ["alist-directories"] }); } });
  const testAlist = useMutation({ mutationFn: () => api("/api/admin/alist/test", { method: "POST", body: JSON.stringify(alistForm) }), onSuccess: () => queryClient.invalidateQueries({ queryKey: ["alist"] }) });
  const saveSystem = useMutation({ mutationFn: () => api("/api/admin/system", { method: "PUT", body: JSON.stringify(systemForm) }), onSuccess: () => queryClient.invalidateQueries({ queryKey: ["system"] }) });
  const addMapping = useMutation({
    mutationFn: () => api(editingMappingId ? `/api/admin/root-mappings/${editingMappingId}` : "/api/admin/root-mappings", { method: editingMappingId ? "PUT" : "POST", body: JSON.stringify({ ...mappingForm, enabled: editingMappingId ? mappings.data?.items.find((item) => item.id === editingMappingId)?.enabled ?? true : true, sort_order: editingMappingId ? mappings.data?.items.find((item) => item.id === editingMappingId)?.sort_order ?? 0 : mappings.data?.items.length ?? 0 }) }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["mappings"] });
      setMappingForm((value) => ({ ...value, display_name: "", alist_path: "" }));
      setSelectedDirectory(null);
      setEditingMappingId(null);
    },
  });
  const toggleMapping = useMutation({ mutationFn: (item: Mapping) => api(`/api/admin/root-mappings/${item.id}`, { method: "PUT", body: JSON.stringify({ content_type: item.content_type, display_name: item.display_name, alist_path: item.alist_path, enabled: !item.enabled, sort_order: item.sort_order }) }), onSuccess: () => queryClient.invalidateQueries({ queryKey: ["mappings"] }) });
  const removeMapping = useMutation({ mutationFn: (id: number) => api(`/api/admin/root-mappings/${id}`, { method: "DELETE" }), onSuccess: () => queryClient.invalidateQueries({ queryKey: ["mappings"] }) });

  const chooseDirectory = (item: DirectoryItem, closePicker = false) => {
    setSelectedDirectory(item);
    setMappingForm({ content_type: inferContentType(item.name), display_name: item.name, alist_path: item.path });
    if (closePicker) setPickerOpen(false);
  };
  const openPicker = () => {
    setBrowserPath("/");
    setSelectedDirectory(mappingForm.alist_path ? { name: pathName(mappingForm.alist_path), path: mappingForm.alist_path, modified: null } : null);
    setPickerOpen(true);
  };
  const editMapping = (item: Mapping) => {
    setEditingMappingId(item.id);
    setMappingForm({ content_type: item.content_type, display_name: item.display_name, alist_path: item.alist_path });
    setSelectedDirectory({ name: item.display_name, path: item.alist_path, modified: null });
  };
  const submitAlist = (event: FormEvent) => { event.preventDefault(); saveAlist.mutate(); };
  const breadcrumbs = browserPath.split("/").filter(Boolean);

  return <AdminShell title="系统"><div className="admin-page system-grid">
    <section className="panel"><h2><Link2 />AList 连接</h2><p className="panel-intro">填写 AList 服务地址和管理员账号。保存后会加密凭据，并自动读取真实网盘目录。</p>
      <div className={`connection-summary ${alist.data?.connection_status ?? "unconfigured"}`}><span className="connection-dot" /><div><strong>{alist.data?.connection_status === "connected" ? "已连接" : alist.data?.connection_status === "disconnected" ? "连接异常" : "尚未配置"}</strong><small>{alist.data?.base_url || "请先填写下方连接信息"}{alist.data?.username ? ` · ${alist.data.username}` : ""}</small><small>{alist.data?.last_test_at ? `最近测试：${new Date(alist.data.last_test_at).toLocaleString("zh-CN")}` : "尚未测试连接"}</small></div></div>
      <form className="form-stack" onSubmit={submitAlist}><label>AList 服务地址<input value={alistForm.base_url} onChange={(e) => setAlistForm({ ...alistForm, base_url: e.target.value })} placeholder="例如 http://192.168.1.20:5244" required /></label><label>管理员账号<input value={alistForm.username} onChange={(e) => setAlistForm({ ...alistForm, username: e.target.value })} placeholder="AList 管理员用户名" required /></label><label>管理员密码<span className="password-field"><input type={showPassword ? "text" : "password"} value={alistForm.password} onChange={(e) => setAlistForm({ ...alistForm, password: e.target.value })} placeholder={alist.data?.has_password ? "已保存；留空即可继续使用" : "输入 AList 管理员密码"} /><button type="button" aria-label={showPassword ? "隐藏密码" : "显示密码"} onClick={() => setShowPassword((value) => !value)}>{showPassword ? <EyeOff /> : <Eye />}</button></span>{alist.data?.has_password && <small className="saved-secret"><CheckCircle2 />服务端已有加密凭据</small>}</label><label className="check"><input type="checkbox" checked={alistForm.remember_credentials} onChange={(e) => setAlistForm({ ...alistForm, remember_credentials: e.target.checked })} />加密保存登录信息（目录读取和同步需要）</label><div className="form-actions"><button type="button" disabled={testAlist.isPending || saveAlist.isPending} onClick={() => testAlist.mutate()}><RefreshCw className={testAlist.isPending ? "spin" : ""} />{testAlist.isPending ? "正在验证…" : "测试连接"}</button><button className="primary" disabled={saveAlist.isPending || testAlist.isPending}><Save />{saveAlist.isPending ? "正在保存…" : "验证并保存"}</button></div>{(testAlist.isSuccess || saveAlist.isSuccess) && <p className="form-success"><CheckCircle2 />已验证 AList 登录并成功读取根目录</p>}{!testAlist.isSuccess && !saveAlist.isSuccess && alist.data?.last_test_message && <p className={alist.data.last_test_status === "success" ? "form-success" : "form-error"}>{alist.data.last_test_message}</p>}{(testAlist.error || saveAlist.error) && <p className="form-error">{(testAlist.error || saveAlist.error)?.message}</p>}</form></section>

    <section className="panel index-and-mapping"><h2><Database />索引状态</h2><dl><div><dt>资源总数</dt><dd>{system.data?.resources ?? 0}</dd></div><div><dt>文件夹数量</dt><dd>{system.data?.folders ?? 0}</dd></div><div><dt>操作日志</dt><dd>{system.data?.operation_logs ?? 0}</dd></div><div><dt>数据库</dt><dd>{system.data?.database ?? "SQLite 3"}</dd></div><div><dt>FTS 索引</dt><dd className="ok-text">已就绪</dd></div></dl>
      <div className="mapping-heading"><div><h3>内容根目录映射</h3><p>从真实 AList 目录中选择，无需手写路径。</p></div>{alist.data?.enabled && <button type="button" className="icon-button" title="重新读取根目录" onClick={() => rootDirectories.refetch()}><RefreshCw /></button>}</div>
      {!alist.data?.enabled ? <div className="mapping-connect-empty"><FolderSearch /><strong>请先连接 AList</strong><span>连接成功后，这里会直接显示真实网盘目录。</span></div> : rootDirectories.isLoading ? <div className="mapping-connect-empty"><RefreshCw className="spin" /><strong>正在读取网盘目录</strong></div> : rootDirectories.error ? <div className="mapping-connect-empty error-state"><FolderSearch /><strong>目录读取失败</strong><span>{rootDirectories.error.message}</span><button type="button" onClick={() => rootDirectories.refetch()}>重新读取</button></div> : <>
        <div className="root-directory-grid">{rootDirectories.data?.items.slice(0, 8).map((item) => <button type="button" key={item.path} className={mappingForm.alist_path === item.path ? "selected" : ""} onClick={() => chooseDirectory(item)}><Folder /><span><strong>{item.name}</strong><small>{item.path}</small></span>{mappingForm.alist_path === item.path ? <Check /> : <ChevronRight />}</button>)}</div>
        <button type="button" className="browse-directory-button" onClick={openPicker}><FolderSearch />浏览根目录及子目录</button>
      </>}

      {mappings.data?.items.length ? <div className="mapping-list existing-mappings">{mappings.data.items.map((item) => <div className={item.enabled ? "" : "disabled"} key={item.id}><span><b>{item.display_name}{!item.enabled && "（已停用）"}</b><small>{contentTypes.find(([value]) => value === item.content_type)?.[1] ?? item.content_type} ← {item.alist_path}</small></span><span className="mapping-row-actions"><button type="button" title="编辑映射" aria-label={`编辑 ${item.display_name} 映射`} onClick={() => editMapping(item)}><Pencil /></button><button type="button" title={item.enabled ? "停用映射" : "启用映射"} aria-label={`${item.enabled ? "停用" : "启用"} ${item.display_name} 映射`} onClick={() => toggleMapping.mutate(item)}><Power /></button><button type="button" title="删除映射" aria-label={`删除 ${item.display_name} 映射`} onClick={() => removeMapping.mutate(item.id)}><Trash2 /></button></span></div>)}</div> : null}

      <form className="mapping-builder" onSubmit={(event) => { event.preventDefault(); addMapping.mutate(); }}>
        <div className="mapping-fields"><label>网站分类<select value={mappingForm.content_type} onChange={(e) => setMappingForm({ ...mappingForm, content_type: e.target.value })}>{contentTypes.map(([value, label]) => <option value={value} key={value}>{label}</option>)}</select></label><label>前台显示名称<input value={mappingForm.display_name} onChange={(e) => setMappingForm({ ...mappingForm, display_name: e.target.value })} placeholder="选择目录后自动填写" /></label></div>
        {mappingForm.alist_path ? <div className="mapping-preview"><span>映射预览</span><strong>网站“{mappingForm.display_name || "未命名"}”资源库</strong><ChevronRight /><b>AList {mappingForm.alist_path}</b></div> : <div className="mapping-preview empty-preview">请先从上方选择一个 AList 文件夹</div>}
        <details className="advanced-path"><summary>高级设置：手动输入路径</summary><label>AList 完整路径<input value={mappingForm.alist_path} onChange={(e) => { const path = e.target.value; setMappingForm({ ...mappingForm, alist_path: path }); setSelectedDirectory(path ? { name: pathName(path), path, modified: null } : null); }} placeholder="例如 /软件" /></label></details>
        <div className="mapping-submit">{editingMappingId && <button type="button" onClick={() => { setEditingMappingId(null); setMappingForm({ content_type: "software", display_name: "", alist_path: "" }); }}>取消编辑</button>}<button className="primary" disabled={!mappingForm.alist_path || !mappingForm.display_name || addMapping.isPending}><FolderPlus />{addMapping.isPending ? "正在保存…" : editingMappingId ? "保存映射修改" : "添加映射"}</button></div>
        {addMapping.error && <p className="form-error">{addMapping.error.message}</p>}
      </form>
    </section>

    <section className="panel"><h2><RefreshCw />自动同步</h2><div className="setting-row"><span><strong>自动同步</strong><small>按间隔低速同步 AList 变化</small></span><input className="toggle" type="checkbox" checked={systemForm.automatic_sync} onChange={(e) => setSystemForm({ ...systemForm, automatic_sync: e.target.checked })} /></div><label className="select-label">同步间隔<select value={systemForm.sync_interval_minutes} onChange={(e) => setSystemForm({ ...systemForm, sync_interval_minutes: Number(e.target.value) })}><option value={180}>3 小时</option><option value={360}>6 小时</option><option value={720}>12 小时</option><option value={1440}>24 小时</option></select></label><div className="setting-row"><span><strong>启动到期检查</strong><small>仅当距离上次成功同步已超过设定周期，才在启动后延迟同步</small></span><input className="toggle" type="checkbox" checked={systemForm.sync_on_startup} onChange={(e) => setSystemForm({ ...systemForm, sync_on_startup: e.target.checked })} /></div><button className="primary" onClick={() => saveSystem.mutate()}><Save />保存同步设置</button></section>
    <section className="panel"><h2><Server />服务信息</h2><dl><div><dt>API 版本</dt><dd>v{system.data?.version ?? "0.3.3"}</dd></div><div><dt>部署模式</dt><dd>Docker Compose</dd></div><div><dt>健康状态</dt><dd className="ok-text">健康</dd></div><div><dt>时区</dt><dd>{system.data?.timezone ?? "Asia/Shanghai"}</dd></div></dl></section>
  </div>

  {pickerOpen && <div className="directory-modal-backdrop" role="presentation" onMouseDown={(event) => { if (event.target === event.currentTarget) setPickerOpen(false); }}><section className="directory-modal" role="dialog" aria-modal="true" aria-labelledby="directory-modal-title"><header><div><h2 id="directory-modal-title">选择 AList 文件夹</h2><p>进入目录查看子文件夹，选中后再确认。</p></div><button type="button" className="icon-button" aria-label="关闭目录选择器" onClick={() => setPickerOpen(false)}><X /></button></header>
    <nav className="directory-breadcrumb" aria-label="目录路径"><button type="button" onClick={() => setBrowserPath("/")}>根目录</button>{breadcrumbs.map((segment, index) => { const path = `/${breadcrumbs.slice(0, index + 1).join("/")}`; return <span key={path}><ChevronRight /><button type="button" onClick={() => setBrowserPath(path)}>{segment}</button></span>; })}</nav>
    <div className="directory-current"><span>当前位置</span><strong>{browserPath}</strong><button type="button" onClick={() => setSelectedDirectory({ name: pathName(browserPath), path: browserPath, modified: null })}>选择当前目录</button></div>
    <div className="directory-list">{browserDirectories.isLoading ? <div className="directory-state"><RefreshCw className="spin" />正在读取目录…</div> : browserDirectories.error ? <div className="directory-state error-state">{browserDirectories.error.message}<button type="button" onClick={() => browserDirectories.refetch()}>重试</button></div> : browserDirectories.data?.items.length ? browserDirectories.data.items.map((item) => <div className={selectedDirectory?.path === item.path ? "directory-row selected" : "directory-row"} key={item.path}><button type="button" className="directory-select" onClick={() => setSelectedDirectory(item)}><Folder /><span><strong>{item.name}</strong><small>{item.path}</small></span>{selectedDirectory?.path === item.path && <Check />}</button><button type="button" className="directory-enter" onClick={() => setBrowserPath(item.path)}>进入<ChevronRight /></button></div>) : <div className="directory-state">当前目录下没有子文件夹，可直接选择当前位置。</div>}</div>
    <footer><span>{selectedDirectory ? <>已选择：<strong>{selectedDirectory.path}</strong></> : "尚未选择目录"}</span><div><button type="button" onClick={() => setPickerOpen(false)}>取消</button><button type="button" className="primary" disabled={!selectedDirectory} onClick={() => selectedDirectory && chooseDirectory(selectedDirectory, true)}>使用此目录</button></div></footer>
  </section></div>}
  </AdminShell>;
}
