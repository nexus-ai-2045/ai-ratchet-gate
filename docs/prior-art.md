# 先行概念との関係

AI Ratchet Gateは既存概念を置き換えるものではなく、複数の考え方を狭い増分安全ゲートへ
組み合わせる。以下は名称の過大主張を避けるための境界でもある。

## Policy as Code

[Open Policy Agent](https://www.openpolicyagent.org/docs)は、構造化入力に対するpolicy decisionを
アプリケーションの強制処理から分離する汎用policy engineである。AI Ratchet Gateも判定と
enforcement pointを分離するが、MVPではOPA/Regoを依存にせず、小さなPython CLI契約を維持する。
CIへのpolicy-as-code適用例は[OPA公式CI/CDガイド](https://www.openpolicyagent.org/docs/cicd)を参照。

## CEGIS-inspired feedback loop

CEGISは候補を生成し、検証器が返すcounterexampleを使って次候補を改善するprogram synthesisの
手法である。起源と一般形は
[MITのProgram Synthesis講義](https://people.csail.mit.edu/asolar/SynthesisCourse2020/Lecture10.htm)
で説明されている。

本ツールはprogram synthesizerではない。人間が発見した反例をrule、fixture、adapterへ変換し、
以後の候補状態へ適用する循環だけを`CEGIS-inspired`と表現する。形式的完全性や正しさは保証しない。

## Shielding-inspired gate

[Shield Synthesis: Runtime Enforcement for Reactive Systems](https://arxiv.org/abs/1501.02573)は、
critical propertyをruntimeで監視し、必要な場合だけ出力を補正するshieldを扱う。

本ツールはruntime出力を自動補正しない。AIやagent runtimeの外側で、commitやCIなどの境界へ
到達した候補状態をallow / denyする点だけを`shielding-inspired`と表現する。

## Architecture fitness functions

[Thoughtworksのfitness function-driven development](https://www.thoughtworks.com/en-au/insights/articles/fitness-function-driven-development)
は、守りたいarchitecture特性を継続的に測定し、変更時のfeedbackへ接続する。本ツールの各adapterは
離散的なfitness functionに相当する。ただし安全軸を総合点へ集約せず、軸ごとの悪化を独立に止める。

`skill.provenance`もこの意味での狭いfitness functionである。tracked skill bundleのpresence、
bundle digest（SHA-256）、宣言されたtool / permissionの拡大だけを観測する。SLSA供給網保証、
Sigstore署名検証、SkillLedger台帳、runtime mediationの代替ではない。

## Receding-horizon / MPC-inspired operation

現在状態と提案された次状態を評価し、一段進んだ後に再観測・再計画する。これは長い自動計画を
一括承認しない運用上の比喩であり、plant model、目的関数、horizon最適化を備えた正式なModel
Predictive Controlではない。

## AIリスク管理との対応

[NIST AI RMF Core](https://airc.nist.gov/airmf-resources/airmf/5-sec-core/)は、利用者等からのfeedbackを
measurementへ統合し、継続的にMeasure / Manageすることを求める。AI Ratchet Gateは、形式化可能な
既知問題についてfeedbackを再実行可能な検査へ変換する実装部品であり、AI RMF全体を実装するものではない。
