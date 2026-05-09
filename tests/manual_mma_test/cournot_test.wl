(* ========================================================
   Cournot Duopoly: 接口验证用最小博弈

   目标：验证整个 Python ↔ Mathematica 数据流。
   - 模型：P = a - q1 - q2，成本 c_i * q_i
   - 求纳什均衡 q1*, q2*
   - 计算利润 pi1, pi2
   - 输出结构化 JSON
   ======================================================== *)

ClearAll["Global`*"];

(* ----------------------------------------------------------
   warnings 用来累积运行中的警告（非致命问题）。
   ---------------------------------------------------------- *)
warnings = {};

(* ----------------------------------------------------------
   参数假设：a, c1, c2 都是正实数；c1, c2 < a 保证内点解。
   ---------------------------------------------------------- *)
$Assumptions = {a > 0, c1 > 0, c2 > 0, c1 < a, c2 < a};

(* ----------------------------------------------------------
   反需求函数和利润函数
   ---------------------------------------------------------- *)
P[q1_, q2_] := a - q1 - q2;
pi1Expr = (P[q1, q2] - c1) * q1;
pi2Expr = (P[q1, q2] - c2) * q2;

(* ----------------------------------------------------------
   求一阶条件并联立求解
   ---------------------------------------------------------- *)
foc1 = D[pi1Expr, q1];
foc2 = D[pi2Expr, q2];

solSet = Solve[{foc1 == 0, foc2 == 0}, {q1, q2}];

(* 检查求解是否成功 *)
status = "success";
failedAt = "";

If[solSet === {} || Length[solSet] == 0,
  status = "failed";
  failedAt = "Solve returned empty";
  AppendTo[warnings, "Solve returned no solutions"];
];

(* 取第一个解（这里只会有一个） *)
If[status === "success",
  sol = solSet[[1]];
  q1Star = q1 /. sol // FullSimplify;
  q2Star = q2 /. sol // FullSimplify;
];

(* ----------------------------------------------------------
   计算均衡利润
   ---------------------------------------------------------- *)
If[status === "success",
  pi1Star = pi1Expr /. sol // FullSimplify;
  pi2Star = pi2Expr /. sol // FullSimplify;
];

(* ----------------------------------------------------------
   Sanity check: 把均衡解代回 FOC，应该是 0
   ---------------------------------------------------------- *)
If[status === "success",
  focResidual1 = (foc1 /. sol) // FullSimplify;
  focResidual2 = (foc2 /. sol) // FullSimplify;
  
  If[focResidual1 =!= 0,
    AppendTo[warnings, 
      "FOC residual for q1 is not zero: " <> ToString[focResidual1, InputForm]
    ];
  ];
  If[focResidual2 =!= 0,
    AppendTo[warnings, 
      "FOC residual for q2 is not zero: " <> ToString[focResidual2, InputForm]
    ];
  ];
];

(* ----------------------------------------------------------
   构造结果对象
   注意：所有数学表达式用 ToString[..., InputForm] 转成 ASCII 字符串
   ---------------------------------------------------------- *)
result = If[status === "success",
  <|
    "scenario_id" -> "cournot_test",
    "status" -> status,
    "model_hash" -> "cournot_v1",
    "warnings" -> warnings,
    "equilibrium" -> <|
      "q1_star" -> ToString[q1Star, InputForm],
      "q2_star" -> ToString[q2Star, InputForm]
    |>,
    "profits" -> <|
      "pi1" -> ToString[pi1Star, InputForm],
      "pi2" -> ToString[pi2Star, InputForm]
    |>,
    "sanity_checks" -> <|
      "foc_residual_q1" -> ToString[focResidual1, InputForm],
      "foc_residual_q2" -> ToString[focResidual2, InputForm]
    |>
  |>,
  (* status != "success" 的分支 *)
  <|
    "scenario_id" -> "cournot_test",
    "status" -> status,
    "failed_at" -> failedAt,
    "warnings" -> warnings
  |>
];

(* ----------------------------------------------------------
   输出到 JSON 文件 + 控制台摘要
   ---------------------------------------------------------- *)
outputPath = FileNameJoin[{DirectoryName[$InputFileName], "cournot_result.json"}];
Export[outputPath, result, "JSON"];

Print["============================================"];
Print["Cournot 求解完成"];
Print["状态: ", status];
If[status === "success",
  Print["q1* = ", q1Star // TraditionalForm];
  Print["q2* = ", q2Star // TraditionalForm];
  Print["pi1 = ", pi1Star // TraditionalForm];
  Print["pi2 = ", pi2Star // TraditionalForm];
  Print["FOC 验证（应为 0）："];
  Print["  q1 残差: ", focResidual1];
  Print["  q2 残差: ", focResidual2];
];
If[Length[warnings] > 0,
  Print["警告："];
  Do[Print["  - ", w], {w, warnings}];
];
Print["结果已写入: ", outputPath];
Print["============================================"];