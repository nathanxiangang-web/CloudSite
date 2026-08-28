import { PublicShell } from "@/components/PublicShell";
import { SiteFooter } from "@/components/SiteFooter";

export default function PrivacyPage() {
  return <PublicShell><div className="page static-page">
    <h1>隐私政策</h1>
    <p>普通访客使用本站无需注册、无需提供个人信息。</p>
    <p>为保障服务运行，系统可能记录基础技术日志，包括：</p>
    <ul>
      <li>基础系统日志</li>
      <li>下载请求事件</li>
      <li>分享访问次数（Share View Count）</li>
      <li>错误日志</li>
    </ul>
    <p>本站不使用广告追踪、指纹识别，不建立用户档案，不收集营销 Cookie。</p>
    <p>以下敏感信息不会被公开：AList 密码与 Token、CloudSite 主密钥（Master Key）、Storage 凭据、访问码哈希。</p>
    <SiteFooter />
  </div></PublicShell>;
}
