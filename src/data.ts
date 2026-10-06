import type { StationSeed } from './types'

export const stationSeeds: StationSeed[] = [
  { id:'ST-101', name:'강남역 2번 출구', district:'강남구', lat:37.4979, lng:127.0276, capacity:30, base:11, bias:-8 },
  { id:'ST-102', name:'삼성역 5번 출구', district:'강남구', lat:37.5088, lng:127.0632, capacity:28, base:23, bias:7 },
  { id:'ST-103', name:'선릉역 3번 출구', district:'강남구', lat:37.5045, lng:127.0490, capacity:24, base:12, bias:-2 },
  { id:'ST-104', name:'잠실역 8번 출구', district:'송파구', lat:37.5133, lng:127.1002, capacity:35, base:6, bias:-10 },
  { id:'ST-105', name:'올림픽공원 평화의문', district:'송파구', lat:37.5209, lng:127.1215, capacity:30, base:25, bias:8 },
  { id:'ST-106', name:'여의도역 1번 출구', district:'영등포구', lat:37.5216, lng:126.9242, capacity:32, base:8, bias:-9 },
  { id:'ST-107', name:'국회의사당역', district:'영등포구', lat:37.5281, lng:126.9179, capacity:26, base:21, bias:6 },
  { id:'ST-108', name:'홍대입구역 2번 출구', district:'마포구', lat:37.5572, lng:126.9236, capacity:38, base:13, bias:-6 },
  { id:'ST-109', name:'상암 DMC역', district:'마포구', lat:37.5760, lng:126.8995, capacity:30, base:26, bias:9 },
  { id:'ST-110', name:'서울역 12번 출구', district:'중구', lat:37.5547, lng:126.9707, capacity:36, base:9, bias:-9, dataHealth:'delayed' },
  { id:'ST-111', name:'시청역 5번 출구', district:'중구', lat:37.5658, lng:126.9769, capacity:24, base:19, bias:5 },
  { id:'ST-112', name:'광화문 시민열린마당', district:'종로구', lat:37.5758, lng:126.9768, capacity:28, base:14, bias:0 },
  { id:'ST-113', name:'혜화역 1번 출구', district:'종로구', lat:37.5838, lng:127.0017, capacity:24, base:5, bias:-8 },
  { id:'ST-114', name:'왕십리역 4번 출구', district:'성동구', lat:37.5613, lng:127.0371, capacity:30, base:24, bias:7 },
  { id:'ST-115', name:'서울숲 관리사무소', district:'성동구', lat:37.5444, lng:127.0374, capacity:32, base:17, bias:1 },
  { id:'ST-116', name:'건대입구역 사거리', district:'광진구', lat:37.5404, lng:127.0692, capacity:34, base:7, bias:-8 },
  { id:'ST-117', name:'천호역 10번 출구', district:'강동구', lat:37.5386, lng:127.1237, capacity:28, base:22, bias:7 },
  { id:'ST-118', name:'노원역 7번 출구', district:'노원구', lat:37.6553, lng:127.0613, capacity:30, base:8, bias:-7 },
  { id:'ST-119', name:'미아사거리역', district:'강북구', lat:37.6132, lng:127.0301, capacity:26, base:20, bias:5 },
  { id:'ST-120', name:'연신내역 3번 출구', district:'은평구', lat:37.6191, lng:126.9211, capacity:28, base:13, bias:-1 },
  { id:'ST-121', name:'신림역 5번 출구', district:'관악구', lat:37.4842, lng:126.9296, capacity:34, base:5, bias:-9 },
  { id:'ST-122', name:'서울대입구역 2번', district:'관악구', lat:37.4813, lng:126.9527, capacity:30, base:24, bias:8 },
  { id:'ST-123', name:'고속터미널 광장', district:'서초구', lat:37.5048, lng:127.0049, capacity:36, base:18, bias:1 },
  { id:'ST-124', name:'목동역 4번 출구', district:'양천구', lat:37.5261, lng:126.8644, capacity:28, base:23, bias:7, dataHealth:'missing' },
]

export const timeOptions = [
  { value: 8, label: '출근 · 08:00' },
  { value: 13, label: '낮 · 13:00' },
  { value: 18, label: '퇴근 · 18:00' },
  { value: 22, label: '야간 · 22:00' },
]
