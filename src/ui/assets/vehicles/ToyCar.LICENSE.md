# ToyCar asset notice

`ToyCar.glb` is the unmodified Khronos glTF Sample Assets ToyCar model.
`ToyCarServo.glb` is a mechanically derived runtime copy that excludes the
showcase fabric and embedded sample-camera scene nodes; its car body, glass,
materials, textures, and geometry are unchanged.

- Source: https://github.com/KhronosGroup/glTF-Sample-Assets/tree/main/Models/ToyCar
- Download: https://raw.githubusercontent.com/KhronosGroup/glTF-Sample-Assets/main/Models/ToyCar/glTF-Binary/ToyCar.glb
- License: Creative Commons Zero v1.0 Universal (CC0-1.0)
- Authors credited upstream: Guido Odendahl and Eric Chadwick
- SHA-256: `01a60862de55cd4b9f3acfab0b0def86451800f9c42467fcd61052c16cb9838c`
- Servo runtime SHA-256: `f5cab0447ef3c0e593987b56ba4d4b5b1978f40cfeddb605e71bb6ef2e529dfb`

Servo uses the self-contained binary glTF as its native 3D vehicle visual. The
vehicle pose and wheel contact remain computed by Servo's descriptor-driven
rigid-body controller; the asset is not a sprite or prerecorded frame.
