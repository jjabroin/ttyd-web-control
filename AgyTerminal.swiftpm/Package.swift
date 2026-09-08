// swift-tools-version: 5.8
import PackageDescription
import AppleProductTypes

let package = Package(
    name: "AgyTerminal",
    platforms: [
        .iOS("16.0")
    ],
    products: [
        .iOSApplication(
            name: "AgyTerminal",
            targets: ["AppModule"],
            displayVersion: "1.0",
            bundleVersion: "1",
            appIcon: .placeholder(icon: .terminal),
            accentColor: .presetColor(.blue),
            supportedDeviceFamilies: [
                .pad,
                .phone
            ],
            supportedInterfaceOrientations: [
                .portrait,
                .landscapeRight,
                .landscapeLeft,
                .portraitUpsideDown(.when(deviceFamilies: [.pad]))
            ],
            capabilities: [
                .photoLibrary(purposeString: "터미널로 전송할 사진을 선택하기 위해 사진 보관함에 접근합니다.")
            ]
        )
    ],
    targets: [
        .executableTarget(
            name: "AppModule",
            path: "."
        )
    ]
)
