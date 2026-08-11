export const EXAMPLE_COMPANIES = [
  {
    name: "苹果公司",
    url: "apple.com",
    hq: "库比蒂诺,美国",
    industry: "消费电子、软件服务",
  },
  {
    name: "字节跳动",
    url: "bytedance.com",
    hq: "北京,中国",
    industry: "互联网",
  },
  {
    name: "宁德时代",
    url: "catl.com",
    hq: "宁德,中国",
    industry: "新能源",
  },
  {
    name: "比亚迪",
    url: "bydglobal.com",
    hq: "深圳,中国",
    industry: "新能源汽车",
  },
  {
    name: "美团",
    url: "meituan.com",
    hq: "北京,中国",
    industry: "本地生活",
  },
  {
    name: "拼多多",
    url: "pinduoduo.com",
    hq: "上海,中国",
    industry: "电商",
  },
  {
    name: "海尔智家",
    url: "haier.com",
    hq: "青岛,中国",
    industry: "家电",
  },
] as const;

export type ExampleCompany = (typeof EXAMPLE_COMPANIES)[number];
