// START OF FILE JS/daopan-data.js (FINAL CORRECTED VERSION V6)

const daopanData = {
    layout: [
        ['zhong', 'ju', 'yi', 'yi', 'ju', 'zhong'],
        ['ju',   'ben', 'tai', 'tai', 'ben',  'ju'   ],
        ['yi',   'tai', 'hole', 'hole','tai',  'yi'   ],
        ['yi',   'tai', 'hole', 'hole','tai',  'yi'   ],
        ['ju',   'ben', 'tai', 'tai', 'ben',  'ju'   ],
        ['zhong', 'ju', 'yi', 'yi', 'ju', 'zhong'],
    ],
    acupointLayout: [
        ['火穴', '土日', '火月', '土穴'], ['土月', '南宫', '西宫', '火日'],
        ['水日', '东宫', '北宫', '风月'], ['风穴', '水月', '风日', '水穴']
    ],
    cellTypeNames: {
        zhong: "重宫", ju: "局宫", yi: "义宫", ben: "本宫", tai: "太宫", hole: "仪宫"
    },
    paths: {
        gates: [ // 八门 (太宫) - 8 cells, 逆时针
            [1, 2], [1, 3], [2, 4], [3, 4], [4, 3], [4, 2], [3, 1], [2, 1]
        ],
        generals: [ // 神将令 (仪宫 + 局宫) - 12 cells, 严格遵循【律令】图顺序
            [2, 2], [1, 0], [0, 1], [2, 3], [0, 4], [1, 5],
            [3, 3], [4, 5], [5, 4], [3, 2], [5, 1], [4, 0]
        ],
        divisions: [ // 十二神部 (重宫 + 义宫) - 12 cells, 【修正为逆时针】
            [0, 0], [2, 0], [3, 0], [5, 0], [5, 2], [5, 3], 
            [5, 5], [3, 5], [2, 5], [0, 5], [0, 3], [0, 2]
        ]
    },
    // --- 【恢复完整数据】为悬停提示提供信息 ---
    divineGenerals: {
        moon: [ // 月家奇将
            { id: 'm1', order: 1, type: '阴', name: '探索者', subName: '越垠', star: '破界星' },
            { id: 'm2', order: 2, type: '阳', name: '革新者', subName: '破曜', star: '裂曜煞' },
            { id: 'm3', order: 3, type: '阴', name: '小丑', subName: '谑枢', star: '谑机星' },
            { id: 'm4', order: 4, type: '阳', name: '天真者', subName: '守昭', star: '众昭煞' },
            { id: 'm5', order: 5, type: '阴', name: '照顾者', subName: '润荄', star: '滋荄星' },
            { id: 'm6', order: 6, type: '阳', name: '英雄', subName: '振锋', star: '振锋煞' },
            { id: 'm7', order: 7, type: '阴', name: '创造者', subName: '形曦', star: '塑曦星' },
            { id: 'm8', order: 8, type: '阳', name: '智者', subName: '鉴渊', star: '鉴渊煞' },
            { id: 'm9', order: 9, type: '阴', name: '情人', subName: '合漪', star: '合漪星' },
            { id: 'm10', order: 10, type: '阳', name: '魔法师', subName: '玄圜', star: '玄圜煞' },
            { id: 'm11', order: 11, type: '阴', name: '统治者', subName: '纲曜', star: '纲曜星' },
            { id: 'm12', order: 12, type: '阳', name: '孤儿', subName: '孤曜', star: '孤曜煞' }
        ],
        sun: [ // 日家偶将
            { id: 's1', order: 1, type: '阳', name: '智者', subName: '鉴渊', star: '明渊星' },
            { id: 's2', order: 2, type: '阴', name: '照顾者', subName: '润荄', star: '荫荄煞' },
            { id: 's3', order: 3, type: '阳', name: '英雄', subName: '振锋', star: '显锋星' },
            { id: 's4', order: 4, type: '阴', name: '天真者', subName: '守昭', star: '立基煞' },
            { id: 's5', order: 5, type: '阳', name: '统治者', subName: '纲曜', star: '纲曜星' },
            { id: 's6', order: 6, type: '阴', name: '革新者', subName: '破曜', star: '裂曜煞' },
            { id: 's7', order: 7, type: '阳', name: '情人', subName: '合漪', star: '合漪星' },
            { id: 's8', order: 8, type: '阴', name: '魔法师', subName: '玄圜', star: '玄圜煞' },
            { id: 's9', order: 9, type: '阳', name: '小丑', subName: '谑枢', star: '谑枢星' },
            { id: 's10', order: 10, type: '阴', name: '创造者', subName: '形曦', star: '藏曦煞' },
            { id: 's11', order: 11, type: '阳', name: '孤儿', subName: '孤曜', star: '孤曜星' },
            { id: 's12', order: 12, type: '阴', name: '探索者', subName: '越垠', star: '越垠煞' }
        ]
    },
    divineDivisions: [
        { id: 'd1', name: '神主键', scripture: '默示录.兴' }, { id: 'd2', name: '刻印键', scripture: '默示录.导' },
        { id: 'd3', name: '精灵键', scripture: '默示录.始' }, { id: 'd4', name: '物语键', scripture: '默示录.高' },
        { id: 'd5', name: '魔物键', scripture: '默示录.答' }, { id: 'd6', name: '崩坏键', scripture: '默示录.阑' },
        { id: 'd7', name: '光音键', scripture: '默示录.结' }, { id: 'd8', name: '契景键', scripture: '默示录.阑' },
        { id: 'd9', name: '天使键', scripture: '默示录.答' }, { id: 'd10', name: '阵灵键', scripture: '默示录.高' },
        { id: 'd11', name: '妖精键', scripture: '默示录.始' }, { id: 'd12', name: '铭纹键', scripture: '默示录.导' }
    ],
    fourEdicts: [
        { id: 'e1', name: '御风令', description: 'A[地(L) > 风(R)] @ B[火(R) > 水(L)]' },
        { id: 'e2', name: '踏影令', description: 'A[风(R) > 地(L)] @ B[水(L) > 火(R)]' },
        { id: 'e3', name: '流光令', description: 'B[水(L) > 火(R)] @ A[风(R) > 地(L)]' },
        { id: 'e4', name: '灵魄令', description: 'B[火(R) > 水(L)] @ A[地(L) > 风(R)]' }
    ],
    eightGates: [ "休门", "生门", "伤门", "杜门", "景门", "死门", "惊门", "开门" ]
};

// END OF FILE JS/daopan-data.js (FINAL CORRECTED VERSION V6)