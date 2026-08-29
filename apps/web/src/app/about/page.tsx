import { PublicShell } from "@/components/PublicShell";
import { SiteFooter } from "@/components/SiteFooter";

export default function AboutPage() {
  return <PublicShell><div className="page static-page">
    <h1>CloudSite</h1>
    <p className="static-lead">把网盘变成好看的资源网站。</p>
    <p>CloudSite 是一个基于 AList 的云端资源网站框架，用于将网盘中的软件、图片、视频、文档和普通文件，整理成可浏览、可搜索、可预览、可下载和可分享的网站。</p>
    <p>AList 负责文件访问与 Storage Driver，CloudSite 负责索引、展示、搜索、合集和分享。</p>
    <h2>核心能力</h2>
    <ul>
      <li>动态目录同步</li>
      <li>资源浏览与分类</li>
      <li>全文搜索</li>
      <li>在线预览（图片 / 视频 / PDF / 文档）</li>
      <li>AList 原生下载链</li>
      <li>精选合集</li>
      <li>分享</li>
    </ul>
    <p className="static-meta">当前版本 v0.1.2</p>
    <SiteFooter />
  </div></PublicShell>;
}
