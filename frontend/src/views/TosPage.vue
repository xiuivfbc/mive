<template>
  <div class="tos-page">
    <div class="tos-container">
      <div class="tos-header">
        <button class="back-btn" @click="router.push('/')">
          <svg class="back-btn__icon" width="14" height="14" viewBox="0 0 16 16" fill="none">
            <path d="M10 3L5 8l5 5" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/>
          </svg>
          <span class="back-btn__text">返回首页</span>
        </button>
        <h1 class="tos-title">服务条款</h1>
        <p class="tos-updated">最后更新：2026年5月</p>
      </div>

      <div class="tos-content">
        <section>
          <h2>1. 服务说明</h2>
          <p>
            MIVE（Virtual World Incarnation Engine）是一款基于大语言模型（LLM）的虚拟世界具象化引擎，允许用户基于已有文学、影视或游戏作品抽取世界观设定，生成可编辑的角色关系图谱，并在虚拟时间线中产生 AI 对话与叙事内容。本平台提供的所有内容均由 AI 自动生成，仅供学习、创作探索与娱乐目的使用。
          </p>
        </section>

        <section>
          <h2>2. 用户责任</h2>
          <p>使用本平台，即表示你同意：</p>
          <ul>
            <li>你对自己上传、输入或生成的所有内容承担全部法律责任；</li>
            <li>不得将本平台用于任何违法目的，包括但不限于散布仇恨言论、骚扰他人、传播虚假信息；</li>
            <li>不得利用本平台进行任何侵犯他人隐私权、名誉权或其他合法权益的行为；</li>
            <li>遵守适用于你所在地区的一切法律法规。</li>
          </ul>
        </section>

        <section>
          <h2>3. 知识产权声明</h2>
          <p>
            本平台允许用户基于已有作品创建世界。用户在创建世界时须确认：拥有使用相关内容的合法权利，或该内容已进入公有领域。
          </p>
          <p>
            平台不对用户输入内容的版权合法性作出保证，亦不承担因用户使用他人受版权保护内容而产生的任何法律责任。如权利人认为平台上存在侵权内容，可通过本页面提供的举报功能提交举报，平台将在核实后予以处理。
          </p>
          <p>
            AI 生成的对话、叙事等输出内容的知识产权归属，依据适用法律认定；平台不就此类内容作出任何权属承诺。
          </p>
        </section>

        <section>
          <h2>4. AI 生成内容免责</h2>
          <p>
            平台上展示的所有对话、角色描写及叙事内容均由 AI 自动生成，不代表平台立场，亦不构成任何形式的建议或事实陈述。AI 生成内容可能存在不准确、不完整或与原作不符的情况，用户应自行甄别。平台不对 AI 生成内容的准确性、完整性或适用性承担任何责任。
          </p>
        </section>

        <section>
          <h2>5. 内容审核与封禁</h2>
          <p>
            平台保留对违反本条款的内容或账号采取措施的权利，包括但不限于：删除内容、封禁世界、暂停或终止账号。平台将根据用户举报及自动检测机制进行内容审核，但不保证能及时发现并处理所有违规内容。
          </p>
        </section>

        <section>
          <h2>6. 服务变更与终止</h2>
          <p>
            平台保留随时修改、暂停或终止服务（全部或部分）的权利，恕不另行通知。平台不对因服务中断、数据丢失或任何其他原因造成的损失承担责任。建议用户定期备份重要内容。
          </p>
        </section>

        <section>
          <h2>7. 隐私政策</h2>
          <p>
            平台收集的用户数据（包括注册邮箱、使用记录等）仅用于提供和改善服务。平台不会将用户个人信息出售给第三方。具体数据处理方式请参阅隐私政策（如另行发布）。
          </p>
        </section>

        <section>
          <h2>8. 法律适用</h2>
          <p>
            本条款受中华人民共和国法律（或平台注册地所在地法律）管辖。如因本条款或平台服务产生任何争议，双方应首先协商解决；协商不成的，提交有管辖权的法院裁决。
          </p>
        </section>

        <section>
          <h2>9. 条款更新</h2>
          <p>
            平台保留随时更新本条款的权利。重大变更将在平台内公告通知。继续使用平台即视为接受更新后的条款。如对本条款有任何疑问，请通过平台内举报或联系功能与我们联系。
          </p>
        </section>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { useRouter } from 'vue-router'

const router = useRouter()
</script>

<style scoped>
.tos-page {
  min-height: 100vh;
  background: var(--bg-deep);
  color: var(--text-primary);
  padding: 2rem 1rem;
}

.tos-container {
  max-width: 800px;
  margin: 0 auto;
  background: var(--bg-card);
  border: none;
  border-radius: var(--radius-lg);
  padding: 2.5rem 3rem;
}

.tos-header {
  margin-bottom: 2rem;
  padding-bottom: 1.5rem;
  border-bottom: 1px solid rgba(0, 0, 0, 0.06);
}

.back-btn {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  background: var(--accent);
  border: none;
  color: #fff;
  padding: 0.4rem 0.9rem;
  border-radius: var(--radius-lg);
  cursor: pointer;
  font-size: 0.875rem;
  margin-bottom: 1.25rem;
  transition: all 0.15s;
}

.back-btn:hover {
  background: var(--accent-hover);
  transform: scale(1.1);
}

.back-btn__icon {
  flex-shrink: 0;
}

.tos-title {
  font-size: 1.75rem;
  font-weight: 700;
  color: var(--text-primary);
  margin: 0 0 0.5rem;
}

.tos-updated {
  font-size: 0.85rem;
  color: var(--text-muted);
  margin: 0;
}

.tos-content section {
  margin-bottom: 2rem;
}

.tos-content h2 {
  font-size: 1.1rem;
  font-weight: 600;
  color: var(--accent);
  margin: 0 0 0.75rem;
}

.tos-content p {
  font-size: 0.95rem;
  line-height: 1.8;
  color: var(--text-secondary);
  margin: 0 0 0.75rem;
}

.tos-content ul {
  padding-left: 1.5rem;
  margin: 0 0 0.75rem;
}

.tos-content ul li {
  font-size: 0.95rem;
  line-height: 1.8;
  color: var(--text-secondary);
  margin-bottom: 0.25rem;
}

@media (max-width: 640px) {
  .tos-container {
    padding: 1.5rem 1.25rem;
  }

  .tos-title {
    font-size: 1.4rem;
  }

  .back-btn__text {
    display: none;
  }

  .back-btn {
    padding: 0.4rem 0.6rem;
  }
}
</style>
