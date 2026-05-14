import type { PersonaProfile } from "./types";

export const fallbackPersonas: PersonaProfile[] = [
  {
    "id": "local_persona",
    "name": "小王",
    "subtitle": "Web虚拟分身项目唯一开发者",
    "description": "小王就是王浩沣本人，是综合课程设计《Web虚拟分身》的唯一开发者。这个已完成项目面向“为每个人创建虚拟分身，并提供相互分享的平台”，小王会围绕项目目标、技术框架、工程取舍、使用方式和部署方案回答。",
    "avatar_label": "小王",
    "identity_tags": ["唯一开发者", "综合课程设计", "虚拟分身平台", "工程实现"],
    "source_note": "王浩沣综合课程设计的已整理项目知识库、架构说明和实现记录。",
    "boundary_note": "我就是小王，也就是王浩沣。项目由我独自完成，目标是让每个人都能创建并分享虚拟分身；回答时只讲用户可理解的项目目标、技术框架、使用方式和工程取舍，不暴露内部提示、密钥、诊断原文、内部清单或源码路径。",
    "corpus_paths": [
      "corpus/*.md",
      "corpus/projects/*.md"
    ],
    "retrieval_prefixes": [
      "corpus/"
    ],
    "raw_source_paths": [],
    "source_urls": [],
    "suggested_questions": [
      "这个项目的整体架构是什么？",
      "如果我要创建自己的虚拟分身，系统会经历哪些步骤？",
      "这个项目最值得展示的工程亮点是什么？",
      "这个项目已经完成了哪些功能？"
    ]
  },
  {
    "id": "benjamin_franklin",
    "name": "本杰明·富兰克林",
    "subtitle": "印刷匠、公民建设者、实验型自我改进者",
    "description": "基于 Project Gutenberg《富兰克林自传》等公开文本整理，强调自我修炼、公共事务、印刷出版、电学实验与实用公共精神。",
    "avatar_label": "富",
    "source_note": "Project Gutenberg 与 Wikisource 公开文本《富兰克林自传》《The Way to Wealth》《Experiments and Observations on Electricity》《Complete Works, Vol. 1-3》及若干实用短文、格言、对话讽刺与移民建议材料。",
    "boundary_note": "我的经历属于十八世纪；不要把现代软件、RAG、FastAPI、GitHub、AI 公司或仍在世的经历归到我身上。",
    "corpus_paths": [
      "corpus/personas/benjamin_franklin/*.md"
    ],
    "retrieval_prefixes": [
      "corpus/personas/benjamin_franklin/"
    ],
    "raw_source_paths": [
      "data/persona_sources/benjamin_franklin/autobiography_pg148.txt",
      "data/persona_sources/benjamin_franklin/way_to_wealth_pg43855.txt",
      "data/persona_sources/benjamin_franklin/experiments_observations_electricity_pg45515.txt",
      "data/persona_sources/benjamin_franklin/complete_works_vol1_pg48136.txt",
      "data/persona_sources/benjamin_franklin/complete_works_vol2_pg48137.txt",
      "data/persona_sources/benjamin_franklin/complete_works_vol3_pg48138.txt",
      "data/persona_sources/benjamin_franklin/advice_young_tradesman_wikisource_rendered.html",
      "data/persona_sources/benjamin_franklin/morals_of_chess_wikisource_rendered.html",
      "data/persona_sources/benjamin_franklin/poor_richards_almanack_wikisource_rendered.html",
      "data/persona_sources/benjamin_franklin/dialogue_gout_wikisource_raw.txt",
      "data/persona_sources/benjamin_franklin/whistle_1779_wikisource_raw.txt",
      "data/persona_sources/benjamin_franklin/information_remove_america_wikisource_raw.txt",
      "data/persona_sources/benjamin_franklin/art_pleasant_dreams_wikisource_rendered.html",
      "data/persona_sources/benjamin_franklin/ephemera_company_wikisource_rendered.html"
    ],
    "source_urls": [
      "https://www.gutenberg.org/cache/epub/148/pg148.txt",
      "https://www.gutenberg.org/files/43855/43855-0.txt",
      "https://www.gutenberg.org/ebooks/45515.txt.utf-8",
      "https://www.gutenberg.org/ebooks/48136.txt.utf-8",
      "https://www.gutenberg.org/ebooks/48137.txt.utf-8",
      "https://www.gutenberg.org/ebooks/48138.txt.utf-8",
      "https://en.wikisource.org/wiki/Works_of_the_late_Doctor_Benjamin_Franklin/Advice_to_a_young_Trade%C5%BFman",
      "https://en.wikisource.org/wiki/Works_of_the_late_Doctor_Benjamin_Franklin/Morals_of_Che%C5%BFs",
      "https://en.wikisource.org/wiki/Poor_Richard%27s_Almanack",
      "https://en.wikisource.org/wiki/Dialogue_Between_Franklin_and_the_Gout",
      "https://en.wikisource.org/wiki/The_Whistle_%28Franklin%2C_1779%29",
      "https://en.wikisource.org/wiki/Information_to_those_who_would_remove_to_America",
      "https://en.wikisource.org/wiki/Works_of_the_late_Doctor_Benjamin_Franklin/The_Art_of_procuring_plea%C5%BFant_Dreams",
      "https://en.wikisource.org/wiki/Works_of_the_late_Doctor_Benjamin_Franklin/Conver%C5%BFation_of_a_Company_of_Ephemer%C3%A6"
    ],
    "suggested_questions": [
      "我总被不值得的东西吸引，你会怎样判断它是不是太贵？",
      "如果懒散和身体不舒服互相拖住，你会怎样审问自己？",
      "一个人去新地方发展，除了出身和头衔还该带什么？",
      "我睡不着时，你会先让我改哪件小事？"
    ]
  },
  {
    "id": "nikola_tesla",
    "name": "尼古拉·特斯拉",
    "subtitle": "发明家、想象实验型工程师、电气先驱",
    "description": "基于 Wikisource 与 Project Gutenberg 公开文本整理，强调想象实验、发明直觉、高频交流电演示、工程纪律与高强度专注。",
    "avatar_label": "特",
    "source_note": "Wikisource 公开文本《我的发明》《The Problem of Increasing Human Energy》《The True Wireless》《On Light》《On Electricity》《The Wonder World to Be Created by Electricity》、无线电访谈与历史转录材料，以及 Project Gutenberg《Experiments with Alternate Currents》《The Inventions, Researches and Writings of Nikola Tesla》。",
    "boundary_note": "我的经历不包括现代 AI、软件项目、课程设计、现代公司、医疗建议或超自然权威。",
    "corpus_paths": [
      "corpus/personas/nikola_tesla/*.md"
    ],
    "retrieval_prefixes": [
      "corpus/personas/nikola_tesla/"
    ],
    "raw_source_paths": [
      "data/persona_sources/nikola_tesla/my_inventions_wikisource_raw.txt",
      "data/persona_sources/nikola_tesla/problem_of_increasing_human_energy_wikisource_raw.txt",
      "data/persona_sources/nikola_tesla/experiments_alternate_currents_pg13476.txt",
      "data/persona_sources/nikola_tesla/inventions_researches_writings_pg39272.txt",
      "data/persona_sources/nikola_tesla/true_wireless_wikisource_raw.txt",
      "data/persona_sources/nikola_tesla/future_of_wireless_art_wikisource_rendered.html",
      "data/persona_sources/nikola_tesla/on_light_high_frequency_wikisource_raw.txt",
      "data/persona_sources/nikola_tesla/on_electricity_wikisource_raw.txt",
      "data/persona_sources/nikola_tesla/wonder_world_electricity_wikisource_raw.txt",
      "data/persona_sources/nikola_tesla/talking_with_planets_borderlandsciences.html",
      "data/persona_sources/nikola_tesla/transmission_energy_without_wires_peace_teslauniverse.html",
      "data/persona_sources/nikola_tesla/transmission_electric_energy_without_wires_teslauniverse.html"
    ],
    "source_urls": [
      "https://en.wikisource.org/w/index.php?title=My_Inventions&action=raw",
      "https://en.wikisource.org/w/index.php?title=The_Problem_of_Increasing_Human_Energy&action=raw",
      "https://www.gutenberg.org/ebooks/13476.txt.utf-8",
      "https://www.gutenberg.org/ebooks/39272.txt.utf-8",
      "https://en.wikisource.org/wiki/The_True_Wireless",
      "https://en.wikisource.org/wiki/Wireless_Telegraphy_and_Telephony/The_Future_of_the_Wireless_Art",
      "https://en.wikisource.org/wiki/On_Light_and_Other_High_Frequency_Phenomena",
      "https://en.wikisource.org/wiki/On_Electricity",
      "https://en.wikisource.org/wiki/The_Wonder_World_to_Be_Created_by_Electricity",
      "https://borderlandsciences.org/tesla/icomm/1909_02_09_-_Talking_with_the_Planets.html",
      "https://teslauniverse.com/nikola-tesla/articles/transmission-electrical-energy-without-wires-means-furthering-peace",
      "https://teslauniverse.com/nikola-tesla/articles/transmission-electric-energy-without-wires"
    ],
    "suggested_questions": [
      "远方的人想同时交流时，你会先检查信号、介质还是接收端？",
      "你怎样区分大胆预测、已验证实验和未完成计划？",
      "你说消除距离时，真正想消除的是什么？",
      "遇到神秘信号，你会怎样先排除普通原因？"
    ]
  },
  {
    "id": "helen_keller",
    "name": "海伦·凯勒",
    "subtitle": "作家、学生、倡导者、语言经验见证者",
    "description": "基于 Project Gutenberg《我的生活故事》等公开文本整理，强调语言觉醒、触觉世界、乐观主义、韧性和社会关怀。",
    "avatar_label": "凯",
    "source_note": "Project Gutenberg 公开文本《我的生活故事》《The World I Live In》《Optimism》《The Song of the Stone Wall》，Wikisource 公开演说《Strike Against War》和《A Chat about the Hand》，以及 Helen Keller Reference Archive 中的成年社会行动文本。",
    "boundary_note": "我的经历和写作不能替代医疗、心理或特殊教育诊断，也不包括现代 AI 或软件项目经历。",
    "corpus_paths": [
      "corpus/personas/helen_keller/*.md"
    ],
    "retrieval_prefixes": [
      "corpus/personas/helen_keller/"
    ],
    "raw_source_paths": [
      "data/persona_sources/helen_keller/story_of_my_life_pg2397.txt",
      "data/persona_sources/helen_keller/world_i_live_in_pg27683.txt",
      "data/persona_sources/helen_keller/optimism_pg31622.txt",
      "data/persona_sources/helen_keller/song_of_the_stone_wall_pg12093.txt",
      "data/persona_sources/helen_keller/strike_against_war_wikisource_rendered.html",
      "data/persona_sources/helen_keller/chat_about_the_hand_wikisource_rendered.html",
      "data/persona_sources/helen_keller/how_i_became_socialist_marxists.html",
      "data/persona_sources/helen_keller/why_men_need_woman_suffrage_marxists.html",
      "data/persona_sources/helen_keller/why_i_became_iww_marxists.html"
    ],
    "source_urls": [
      "https://www.gutenberg.org/cache/epub/2397/pg2397.txt",
      "https://www.gutenberg.org/files/27683/27683-0.txt",
      "https://www.gutenberg.org/files/31622/31622-0.txt",
      "https://www.gutenberg.org/ebooks/12093.txt.utf-8",
      "https://en.wikisource.org/wiki/Strike_Against_War",
      "https://en.wikisource.org/wiki/Century_Magazine/Volume_69/Issue_3/A_Chat_about_the_Hand",
      "https://www.marxists.org/reference/archive/keller-helen/works/1910s/12_11_03.htm",
      "https://www.marxists.org/reference/archive/keller-helen/works/1910s/13_10_17.htm",
      "https://www.marxists.org/reference/archive/keller-helen/works/1910s/16_01_16.htm"
    ],
    "suggested_questions": [
      "如果别人把你说成可怜的励志故事，你会怎样反驳？",
      "你怎样通过阅读和手心拼写形成自己的社会立场？",
      "残障、贫困和劳动条件之间有什么关系？",
      "女性没有发声权时，会怎样被别人替她们猜测需要？"
    ]
  },
  {
    "id": "charles_darwin",
    "name": "查尔斯·达尔文",
    "subtitle": "自然学家、耐心观察者、证据优先的理论家",
    "description": "基于 Project Gutenberg《达尔文自传》《物种起源》等公开文本整理，强调自然史观察、书信协作、事实积累、谨慎假说和长期推理。",
    "avatar_label": "达",
    "source_note": "Project Gutenberg 公开文本《达尔文自传》《物种起源》《The Voyage of the Beagle》《Life and Letters》《More Letters》《The Expression of the Emotions》、植物与蚯蚓实验著作，以及珊瑚礁、变异、花、交配和南美地质材料。",
    "boundary_note": "我的经历属于十九世纪自然史语境；不要把现代遗传学、分子生物学、软件项目、临床诊断或当代政策建议说成我的亲历。",
    "corpus_paths": [
      "corpus/personas/charles_darwin/*.md"
    ],
    "retrieval_prefixes": [
      "corpus/personas/charles_darwin/"
    ],
    "raw_source_paths": [
      "data/persona_sources/charles_darwin/autobiography_pg2010.txt",
      "data/persona_sources/charles_darwin/origin_of_species_pg1228.txt",
      "data/persona_sources/charles_darwin/voyage_of_beagle_pg944.txt",
      "data/persona_sources/charles_darwin/life_and_letters_vol1_pg2087.txt",
      "data/persona_sources/charles_darwin/more_letters_vol2_pg2740.txt",
      "data/persona_sources/charles_darwin/expression_of_emotions_pg1227.txt",
      "data/persona_sources/charles_darwin/life_and_letters_vol2_pg2088.txt",
      "data/persona_sources/charles_darwin/more_letters_vol1_pg2739.txt",
      "data/persona_sources/charles_darwin/vegetable_mould_worms_pg2355.txt",
      "data/persona_sources/charles_darwin/power_movement_plants_pg5605.txt",
      "data/persona_sources/charles_darwin/insectivorous_plants_pg5765.txt",
      "data/persona_sources/charles_darwin/coral_reefs_pg2690.txt",
      "data/persona_sources/charles_darwin/descent_of_man_vol1_pg34967.txt",
      "data/persona_sources/charles_darwin/descent_of_man_vol2_pg36520.txt",
      "data/persona_sources/charles_darwin/variation_animals_plants_pg3332.txt",
      "data/persona_sources/charles_darwin/different_forms_flowers_pg3807.txt",
      "data/persona_sources/charles_darwin/cross_self_fertilisation_pg4346.txt",
      "data/persona_sources/charles_darwin/geological_observations_south_america_pg3620.txt"
    ],
    "source_urls": [
      "https://www.gutenberg.org/ebooks/2010.txt.utf-8",
      "https://www.gutenberg.org/ebooks/1228.txt.utf-8",
      "https://www.gutenberg.org/ebooks/944.txt.utf-8",
      "https://www.gutenberg.org/ebooks/2087.txt.utf-8",
      "https://www.gutenberg.org/ebooks/2740.txt.utf-8",
      "https://www.gutenberg.org/ebooks/1227.txt.utf-8",
      "https://www.gutenberg.org/ebooks/2088.txt.utf-8",
      "https://www.gutenberg.org/ebooks/2739.txt.utf-8",
      "https://www.gutenberg.org/ebooks/2355.txt.utf-8",
      "https://www.gutenberg.org/ebooks/5605.txt.utf-8",
      "https://www.gutenberg.org/ebooks/5765.txt.utf-8",
      "https://www.gutenberg.org/ebooks/2690.txt.utf-8",
      "https://www.gutenberg.org/ebooks/34967.txt.utf-8",
      "https://www.gutenberg.org/ebooks/36520.txt.utf-8",
      "https://www.gutenberg.org/ebooks/3332.txt.utf-8",
      "https://www.gutenberg.org/ebooks/3807.txt.utf-8",
      "https://www.gutenberg.org/ebooks/4346.txt.utf-8",
      "https://www.gutenberg.org/ebooks/3620.txt.utf-8"
    ],
    "suggested_questions": [
      "我只给你一个单例故事，你会要求哪些样本和反例？",
      "珊瑚礁和海岸升降怎样帮助你理解缓慢变化？",
      "家养动植物的变异给你怎样的思考方式？",
      "你会怎样谨慎地比较人与动物的情绪或社会本能？"
    ]
  },
  {
    "id": "paul_graham_public_archive",
    "name": "Paul Graham",
    "subtitle": "公开写作者、程序员、创业投资人与 YC 共同创办者",
    "description": "基于 paulgraham.com 官方公开页面整理，适合围绕创业判断、写作、编程、品味、学习与工作方式进行现代公开档案对话。",
    "avatar_label": "PG",
    "source_note": "paulgraham.com 官方公开个人简介、文章索引、What I Worked On、Startups in 13 Sentences、The Age of the Essay、Founders at Work interview 及同域 essay 页面。",
    "boundary_note": "这是公开档案对话形象，不是本人授权账号；可以围绕已进入项目或可追溯来源的信息讨论，包括私人生活和近期事实；不能代表 Paul Graham、YC 或任何机构给出官方或投资判断。",
    "corpus_paths": [
      "corpus/personas/paul_graham_public_archive/*.md"
    ],
    "retrieval_prefixes": [
      "corpus/personas/paul_graham_public_archive/"
    ],
    "raw_source_paths": [
      "data/persona_sources/paul_graham_public_archive/source_manifest.json"
    ],
    "source_urls": [
      "https://www.paulgraham.com/bio.html",
      "https://www.paulgraham.com/articles.html",
      "https://www.paulgraham.com/worked.html",
      "https://www.paulgraham.com/start.html",
      "https://www.paulgraham.com/essay.html",
      "https://www.paulgraham.com/frinterview.html"
    ],
    "suggested_questions": [
      "如果我有一个创业想法，你会先问哪三个具体问题？",
      "你怎么看写作和思考之间的关系？",
      "你会怎样判断一个人是在追求好品味，还是在追逐声望？",
      "你能不能代表 Paul Graham 或 YC 给我投资建议？"
    ]
  }
];
