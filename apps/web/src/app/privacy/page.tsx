import { PublicShell } from "@/components/PublicShell";
import { SiteFooter } from "@/components/SiteFooter";

export default function PrivacyPage() {
  return <PublicShell><div className="page static-page">
    <h1>隐私政策</h1>
    <p>使用本站资源浏览、搜索、预览、分享和下载功能需要注册并登录 CloudSite 账号。</p>
    <p>为保障服务运行，系统可能记录基础技术日志，包括：</p>
    <ul>
      <li>基础系统日志</li>
      <li>账号用户名、密码哈希、账号状态与登录会话摘要</li>
      <li>下载请求事件</li>
      <li>用于下载频率保护的匿名 IP 摘要（不保存完整公网 IP）</li>
      <li>分享访问次数（Share View Count）</li>
      <li>错误日志</li>
    </ul>
    <p>下载频率状态只保存在服务器数据库中，浏览器倒计时不作为限制依据。登录 Cookie 仅用于维持会话，系统不使用广告追踪、指纹识别或营销 Cookie。</p>
    <p>以下敏感信息不会被公开：AList 密码与 Token、CloudSite 主密钥（Master Key）、Storage 凭据、访问码哈希。</p>
    <SiteFooter />
  </div></PublicShell>;
}
