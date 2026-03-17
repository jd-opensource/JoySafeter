export interface ExampleItem {
  id: string
  title: string
  description: string
  prompt: string
  icon: string
  mode?: string
}

export interface ExampleScene {
  id: string
  label: string
  examples: ExampleItem[]
}

export const exampleScenes: ExampleScene[] = [
  {
    id: 'quick-start',
    label: 'examples.quickStart',
    examples: [
      {
        id: 'project-plan',
        title: 'examples.projectPlan',
        description: 'examples.projectPlanDesc',
        prompt: '帮我创建一个网站改版项目的详细计划，包括设计、开发和测试阶段的时间线和关键里程碑',
        icon: '🚀',
      },
      {
        id: 'email-writing',
        title: 'examples.emailWriting',
        description: 'examples.emailWritingDesc',
        prompt: '写一封向客户汇报项目进度的专业邮件，需要包含本周完成的工作和下周计划',
        icon: '📧',
      },
      {
        id: 'goal-setting',
        title: 'examples.goalSetting',
        description: 'examples.goalSettingDesc',
        prompt: '帮我制定这个季度的OKR目标，包括3个关键目标和对应的关键结果',
        icon: '🎯',
      },
    ],
  },
  {
    id: 'creative',
    label: 'examples.creative',
    examples: [
      {
        id: 'product-ideas',
        title: 'examples.productIdeas',
        description: 'examples.productIdeasDesc',
        prompt: '生成10个智能家居产品的创新点子，要考虑环保和节能因素',
        icon: '💡',
      },
      {
        id: 'copywriting',
        title: 'examples.copywriting',
        description: 'examples.copywritingDesc',
        prompt: '为一款健身App创作5个吸引人的广告标语，风格要年轻有活力',
        icon: '✍️',
      },
      {
        id: 'design-concept',
        title: 'examples.designConcept',
        description: 'examples.designConceptDesc',
        prompt: '为一个科技公司Logo设计提供3个不同的创意方向和设计理念',
        icon: '🎨',
      },
    ],
  },
  {
    id: 'data-analysis',
    label: 'examples.dataAnalysis',
    examples: [
      {
        id: 'sales-analysis',
        title: 'examples.salesAnalysis',
        description: 'examples.salesAnalysisDesc',
        prompt: '帮我分析Q4销售数据，创建可视化图表并找出增长趋势和异常点',
        icon: '📊',
        mode: 'data',
      },
      {
        id: 'user-insights',
        title: 'examples.userInsights',
        description: 'examples.userInsightsDesc',
        prompt: '从用户反馈中提取关键痛点和改进建议，按优先级分类',
        icon: '💭',
      },
      {
        id: 'competitor-analysis',
        title: 'examples.competitorAnalysis',
        description: 'examples.competitorAnalysisDesc',
        prompt: '对比三款竞品的功能特性和价格，制作详细的对比分析表',
        icon: '📈',
      },
    ],
  },
  {
    id: 'content-creation',
    label: 'examples.contentCreation',
    examples: [
      {
        id: 'documentation',
        title: 'examples.documentation',
        description: 'examples.documentationDesc',
        prompt: '创建一个产品功能说明文档模板，包含概述、功能列表和使用指南',
        icon: '📄',
        mode: 'docs',
      },
      {
        id: 'presentation',
        title: 'examples.presentation',
        description: 'examples.presentationDesc',
        prompt: '为产品发布会制作演示文稿大纲，包括开场、产品介绍和结束',
        icon: '🎤',
        mode: 'slides',
      },
      {
        id: 'tutorial',
        title: 'examples.tutorial',
        description: 'examples.tutorialDesc',
        prompt: '编写一份Python入门教程的目录结构，包含基础语法、数据类型和实战项目',
        icon: '📚',
      },
    ],
  },
]
