# Servo

**Simulation Environment for Robotic Validation and Optimization**

Servo is an autonomous validation and training workbench for physical AI. Give it a policy, a robot or vehicle configuration, a sensor rig, and recordings of reality. Servo turns those inputs into executable simulation worlds, runs the real policy inside them, discovers capability failures, investigates their causes, creates targeted experiences, retrains through supported adapters, and independently decides whether a new checkpoint is safe to promote.

Servo is being developed for the [All Things Agentic Hackathon](https://allthingsagentichackathon.devpost.com/) in the **Taskmaster** track.

> Project status: early hackathon prototype and product-design phase. The repository currently contains a minimal Qt/QML desktop shell and design research. The autonomous validation loop is not implemented yet.

## The core loop

```text
Model -> Simulate -> Detect failure -> Diagnose cause -> Generate experience
      -> Train -> Hidden exam -> Regression test -> Accept/reject checkpoint
      -> Update Reality Debt -> Select the next weakness -> Repeat
```

The important product is the capability-closing loop, not a Gaussian-splat viewer. Gaussian reconstruction provides photorealistic sensor rendering; deterministic geometry and physics remain responsible for collisions, dynamics, and controllable actors.

## Product principles

- **Action over chat:** the agent runs experiments and changes the development state instead of merely describing a failure.
- **Causal diagnosis:** it tests hypotheses with counterfactual runs before choosing a training plan.
- **Independent proof:** training scenarios and hidden examination scenarios stay separate.
- **Regression protection:** a checkpoint is rejected when it damages previously demonstrated capabilities.
- **Reality Debt:** the UI maintains an evidence-backed map of what the policy can and cannot handle.
- **Missing-reality acquisition:** when existing worlds cannot teach a capability, Servo searches authorized recordings or produces a precise capture mission.
- **Honest adapter boundaries:** Servo can execute and evaluate policies through adapters. Autonomous retraining is available only when a policy exposes a supported training interface.

## Planned architecture

| Layer | Direction |
| --- | --- |
| Desktop experience | Qt 6, QML, and C++ |
| Agent orchestration | Python, Google ADK, Gemini through Vertex AI, and the Google GenAI SDK |
| Durable workflow state | Firestore and Pub/Sub |
| Run artifacts | Cloud Storage |
| GPU work | Isolated reconstruction/training workers on Google Cloud |
| Rendering | Gaussian appearance plus a high-performance C++/CUDA/Vulkan path where needed |
| Physics | Deterministic adapters such as CARLA or MuJoCo rather than Gaussian splats |
| Policy integration | Explicit inference, evaluation, and optional training adapters |

## Repository layout

```text
.
|-- Main.qml              # Current Qt Quick application shell
|-- main.cpp              # Qt application entry point
|-- CMakeLists.txt        # Qt/CMake project definition
|-- importedcontent/      # Reserved for approved imported design assets
`-- docs/                 # Product and hackathon research
```

## Development status

No production build or model-training workflow is available yet. Build, cloud deployment, and reproducibility instructions will be added with the first runnable vertical slice. Nothing in this repository should be used to control a real vehicle or robot.

## Qt and open-source licensing

Servo is developed with the **Qt Community Edition**, using **Qt 6 and QML/Qt Quick**. Qt is dual-licensed. The majority of Qt modules are available under LGPLv3 and GPLv3, while some modules are available only under GPLv3 for open-source use. Servo therefore chooses the **GNU General Public License v3.0 only (`GPL-3.0-only`)** for its own source code.

Using GPLv3 does not remove the need to track the licenses of the exact Qt modules, tools, examples, and third-party components that are distributed with Servo. See Qt's [official licensing overview](https://doc.qt.io/qt-6/licensing.html), [open-source obligations](https://www.qt.io/development/open-source-lgpl-obligations), and the [GPLv3 license text](https://www.gnu.org/licenses/gpl-3.0.html). This note is informational, not legal advice.

The development repository is private during the active hackathon. Authorized hackathon reviewers can be granted access when the submission is prepared.

## License

Servo is licensed under the [GNU General Public License v3.0 only](LICENSE).
