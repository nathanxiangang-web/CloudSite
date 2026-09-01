import { PublicShell } from "@/components/PublicShell";
import { SiteFooter } from "@/components/SiteFooter";
import Link from "next/link";

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
    <h2>投稿与合作</h2>
    <p>欢迎分享优质软件、图片、视频、文档及其他资源。投稿邮箱：<a href="mailto:nathxo@outlook.com">nathxo@outlook.com</a>。</p>
    <p>也可以前往 <Link href="/submit">资源投稿</Link> 页面生成标准投稿模板。CloudSite 不接收用户直接上传，也不会保存邮箱凭据。</p>
    <p className="static-meta">当前版本 v0.3.0</p>
    <SiteFooter />
  </div></PublicShell>;
}
