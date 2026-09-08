import SwiftUI
import WebKit
import PhotosUI
import UniformTypeIdentifiers

// MARK: - App Main Entry
@main
struct AgyTerminalApp: App {
    var body: some Scene {
        WindowGroup {
            ContentView()
                .preferredColorScheme(.dark)
        }
    }
}

// MARK: - Models
struct AttachedFile: Identifiable {
    let id = UUID()
    let name: String
    let sizeText: String
    let data: Data
    let image: UIImage?
    let mimeType: String
}

// MARK: - View Model
@MainActor
final class TerminalViewModel: ObservableObject {
    @Published var serverURL: String {
        didSet {
            UserDefaults.standard.set(serverURL, forKey: "agy_server_url")
        }
    }
    @Published var barMode: Int { // 0: 숨김, 1: 1줄, 2: 2줄
        didSet {
            UserDefaults.standard.set(barMode, forKey: "agy_bar_mode")
        }
    }
    @Published var inputText: String = ""
    @Published var attachedFile: AttachedFile? = nil
    @Published var isUploading: Bool = false
    @Published var errorMessage: String? = nil
    @Published var reloadTrigger: UUID = UUID()

    init() {
        let savedURL = UserDefaults.standard.string(forKey: "agy_server_url")
        self.serverURL = savedURL ?? "http://100.107.195.21:7681"
        let savedMode = UserDefaults.standard.object(forKey: "agy_bar_mode") as? Int
        self.barMode = savedMode ?? 2
    }

    func triggerHaptic() {
        let generator = UIImpactFeedbackGenerator(style: .light)
        generator.prepare()
        generator.impactOccurred()
    }

    func reload() {
        reloadTrigger = UUID()
    }

    // MARK: - Terminal Commands & Key Sequences
    func sendKey(_ seq: String) {
        triggerHaptic()
        sendRaw(seq)
    }

    func sendRaw(_ text: String) {
        guard let url = URL(string: "\(cleanServerURL)/input") else { return }
        var request = URLRequest(url: url)
        request.httpMethod = "POST"
        request.setValue("text/plain; charset=utf-8", forHTTPHeaderField: "Content-Type")
        request.httpBody = text.data(using: .utf8)

        URLSession.shared.dataTask(with: request) { _, _, _ in }.resume()
    }

    func submitPrompt() {
        let textToSend = inputText.trimmingCharacters(in: .whitespacesAndNewlines)
        triggerHaptic()

        if let attachment = attachedFile {
            // 파일 업로드 후 [파일 절대 경로] [사용자 프롬프트] 전송
            uploadFileAndSend(attachment: attachment, promptText: textToSend)
        } else {
            // 텍스트 단독 전송
            inputText = ""
            sendRaw(textToSend + "\r")
        }
    }

    private var cleanServerURL: String {
        var base = serverURL.trimmingCharacters(in: .whitespacesAndNewlines)
        if base.hasSuffix("/") {
            base.removeLast()
        }
        if !base.lowercased().hasPrefix("http://") && !base.lowercased().hasPrefix("https://") {
            base = "http://" + base
        }
        return base
    }

    private func uploadFileAndSend(attachment: AttachedFile, promptText: String) {
        guard let uploadURL = URL(string: "\(cleanServerURL)/upload") else {
            errorMessage = "잘못된 서버 주소입니다."
            return
        }

        isUploading = true
        let boundary = "Boundary-\(UUID().uuidString)"
        var request = URLRequest(url: uploadURL)
        request.httpMethod = "POST"
        request.setValue("multipart/form-data; boundary=\(boundary)", forHTTPHeaderField: "Content-Type")

        var body = Data()
        body.append("--\(boundary)\r\n".data(using: .utf8)!)
        body.append("Content-Disposition: form-data; name=\"file\"; filename=\"\(attachment.name)\"\r\n".data(using: .utf8)!)
        body.append("Content-Type: \(attachment.mimeType)\r\n\r\n".data(using: .utf8)!)
        body.append(attachment.data)
        body.append("\r\n--\(boundary)--\r\n".data(using: .utf8)!)

        URLSession.shared.uploadTask(with: request, from: body) { [weak self] data, response, error in
            Task { @MainActor in
                guard let self = self else { return }
                self.isUploading = false

                if let error = error {
                    self.errorMessage = "업로드 실패: \(error.localizedDescription)"
                    return
                }

                guard let data = data,
                      let json = try? JSONSerialization.jsonObject(with: data) as? [String: Any],
                      let remotePath = json["path"] as? String else {
                    self.errorMessage = "서버 응답 처리 실패"
                    return
                }

                // 파일 전송 성공: [파일 경로] [내용] 조합하여 터미널 주입
                let combined = promptText.isEmpty ? remotePath : "\(remotePath) \(promptText)"
                self.attachedFile = nil
                self.inputText = ""
                self.sendRaw(combined + "\r")
            }
        }.resume()
    }
}

// MARK: - Main Content View
struct ContentView: View {
    @StateObject private var vm = TerminalViewModel()
    @State private var selectedPhotoItem: PhotosPickerItem? = nil
    @State private var showFilePicker = false
    @State private var showSettings = false
    @State private var dragYOffset: CGFloat = 0

    var body: some View {
        ZStack {
            Color(red: 0.08, green: 0.08, blue: 0.09).ignoresSafeArea()

            VStack(spacing: 0) {
                // 상단 네비게이션 헤더
                HStack {
                    HStack(spacing: 6) {
                        Image(systemName: "terminal.fill")
                            .font(.system(size: 14, weight: .semibold))
                            .foregroundColor(.green)
                        Text("AGY Terminal")
                            .font(.system(size: 14, weight: .bold, design: .monospaced))
                            .foregroundColor(.white)
                    }

                    Spacer()

                    Button {
                        vm.triggerHaptic()
                        vm.reload()
                    } label: {
                        Image(systemName: "arrow.clockwise")
                            .font(.system(size: 13, weight: .medium))
                            .foregroundColor(.gray)
                            .padding(6)
                    }

                    Button {
                        vm.triggerHaptic()
                        showSettings.toggle()
                    } label: {
                        Image(systemName: "gearshape.fill")
                            .font(.system(size: 13, weight: .medium))
                            .foregroundColor(.gray)
                            .padding(6)
                    }
                }
                .padding(.horizontal, 14)
                .padding(.vertical, 6)
                .background(Color(red: 0.11, green: 0.11, blue: 0.12))

                // 터미널 본문 (WebKit xterm 뷰)
                TerminalWebView(serverURL: vm.serverURL, reloadTrigger: vm.reloadTrigger)
                    .frame(maxWidth: .infinity, maxHeight: .infinity)

                // 하단 컨트롤 패널 (미리보기 + 당기기 핸들 + 가변 단축키 + 입력창)
                VStack(spacing: 0) {
                    // 첨부파일 카톡 스타일 미리보기 바
                    if let file = vm.attachedFile {
                        HStack(spacing: 10) {
                            if let img = file.image {
                                Image(uiImage: img)
                                    .resizable()
                                    .scaledToFill()
                                    .frame(width: 36, height: 36)
                                    .cornerRadius(6)
                                    .overlay(RoundedRectangle(cornerRadius: 6).stroke(Color.white.opacity(0.2), lineWidth: 1))
                            } else {
                                ZStack {
                                    RoundedRectangle(cornerRadius: 6)
                                        .fill(Color.white.opacity(0.1))
                                        .frame(width: 36, height: 36)
                                    Text("📄")
                                        .font(.system(size: 18))
                                }
                            }

                            VStack(alignment: .leading, spacing: 2) {
                                Text(file.name)
                                    .font(.system(size: 12, weight: .medium))
                                    .foregroundColor(.white)
                                    .lineLimit(1)
                                Text(file.sizeText)
                                    .font(.system(size: 10))
                                    .foregroundColor(.gray)
                            }

                            Spacer()

                            Button {
                                vm.triggerHaptic()
                                vm.attachedFile = nil
                            } label: {
                                Image(systemName: "xmark.circle.fill")
                                    .font(.system(size: 18))
                                    .foregroundColor(.gray)
                            }
                        }
                        .padding(.horizontal, 12)
                        .padding(.vertical, 6)
                        .background(Color(red: 0.14, green: 0.15, blue: 0.18))
                        .transition(.move(edge: .bottom).combined(with: .opacity))
                    }

                    // 0~2줄 조절 당기기 제스처 핸들
                    HandleBar(barMode: $vm.barMode, dragOffset: $dragYOffset) {
                        vm.triggerHaptic()
                    }

                    // 단축키 영역 (0줄/1줄/2줄 가변)
                    if vm.barMode > 0 {
                        Group {
                            if vm.barMode == 2 {
                                TwoRowKeyCluster(vm: vm)
                            } else {
                                SingleRowKeyCluster(vm: vm)
                            }
                        }
                        .padding(.horizontal, 12)
                        .padding(.bottom, 4)
                        .transition(.opacity)
                    }

                    // 하단 텍스트 입력 바 (+ 버튼 / 텍스트필드 / 전송)
                    HStack(spacing: 8) {
                        // [+] 첨부 메뉴 (사진 라이브러리 / 파일 선택)
                        Menu {
                            Button {
                                selectedPhotoItem = nil
                            } label: {
                                Label("사진 보관함", systemImage: "photo.on.rectangle")
                            }
                            .overlay(
                                PhotosPicker(selection: $selectedPhotoItem, matching: .images) {
                                    Color.clear
                                }
                            )

                            Button {
                                showFilePicker = true
                            } label: {
                                Label("파일 선택", systemImage: "folder")
                            }
                        } label: {
                            ZStack {
                                RoundedRectangle(cornerRadius: 6)
                                    .fill(LinearGradient(colors: [Color(white: 0.20), Color(white: 0.14)], startPoint: .top, endPoint: .bottom))
                                    .overlay(RoundedRectangle(cornerRadius: 6).stroke(Color.white.opacity(0.12), lineWidth: 1))
                                    .frame(width: 36, height: 34)

                                Text("+")
                                    .font(.system(size: 20, weight: .light))
                                    .foregroundColor(.white)
                            }
                        }

                        // 한글 입력창
                        TextField("입력 후 전송...", text: $inputText)
                            .font(.system(size: 15, design: .monospaced))
                            .foregroundColor(.white)
                            .padding(.horizontal, 10)
                            .frame(height: 34)
                            .background(Color(white: 0.16))
                            .cornerRadius(6)
                            .overlay(RoundedRectangle(cornerRadius: 6).stroke(Color.white.opacity(0.15), lineWidth: 1))
                            .onSubmit {
                                vm.submitPrompt()
                            }

                        // 전송 버튼
                        Button {
                            vm.submitPrompt()
                        } label: {
                            HStack(spacing: 3) {
                                if vm.isUploading {
                                    ProgressView()
                                        .progressViewStyle(CircularProgressViewStyle(tint: .white))
                                        .scaleEffect(0.7)
                                } else {
                                    Text("전송↵")
                                        .font(.system(size: 13, weight: .medium))
                                }
                            }
                            .foregroundColor(.white)
                            .padding(.horizontal, 12)
                            .frame(height: 34)
                            .background(Color(red: 0.16, green: 0.22, blue: 0.32))
                            .cornerRadius(6)
                            .overlay(RoundedRectangle(cornerRadius: 6).stroke(Color(red: 0.24, green: 0.33, blue: 0.48), lineWidth: 1))
                        }
                        .disabled(vm.isUploading)
                    }
                    .padding(.horizontal, 10)
                    .padding(.vertical, 6)
                }
                .background(Color(red: 0.09, green: 0.09, blue: 0.10))
            }
        }
        // PhotosPicker 선택 감지
        .onChange(of: selectedPhotoItem) { newItem in
            Task {
                if let item = newItem,
                   let data = try? await item.loadTransferable(type: Data.self) {
                    let image = UIImage(data: data)
                    let sizeStr = ByteCountFormatter.string(fromByteCount: Int64(data.count), countStyle: .file)
                    await MainActor.run {
                        vm.attachedFile = AttachedFile(
                            name: "photo_\(Int(Date().timeIntervalSince1970)).jpg",
                            sizeText: sizeStr,
                            data: data,
                            image: image,
                            mimeType: "image/jpeg"
                        )
                        vm.triggerHaptic()
                    }
                }
            }
        }
        // FileImporter 파일 선택 감지
        .fileImporter(isPresented: $showFilePicker, allowedContentTypes: [.item]) { result in
            switch result {
            case .success(let url):
                if url.startAccessingSecurityScopedResource() {
                    defer { url.stopAccessingSecurityScopedResource() }
                    if let data = try? Data(contentsOf: url) {
                        let sizeStr = ByteCountFormatter.string(fromByteCount: Int64(data.count), countStyle: .file)
                        let image = UIImage(data: data)
                        let mime = UTType(filenameExtension: url.pathExtension)?.preferredMIMEType ?? "application/octet-stream"
                        vm.attachedFile = AttachedFile(
                            name: url.lastPathComponent,
                            sizeText: sizeStr,
                            data: data,
                            image: image,
                            mimeType: mime
                        )
                        vm.triggerHaptic()
                    }
                }
            case .failure(let error):
                vm.errorMessage = "파일 로드 실패: \(error.localizedDescription)"
            }
        }
        // 서버 주소 설정 팝업
        .sheet(isPresented: $showSettings) {
            ServerSettingsView(vm: vm, isPresented: $showSettings)
        }
        .alert("알림", isPresented: Binding(get: { vm.errorMessage != nil }, set: { if !$0 { vm.errorMessage = nil } })) {
            Button("확인", role: .cancel) { vm.errorMessage = nil }
        } message: {
            Text(vm.errorMessage ?? "")
        }
    }
}

// MARK: - Handle Bar with Pull Gestures
struct HandleBar: View {
    @Binding var barMode: Int
    @Binding var dragOffset: CGFloat
    var onHaptic: () -> Void

    var body: some View {
        HStack {
            Spacer()
            Capsule()
                .fill(Color.white.opacity(0.35))
                .frame(width: 36, height: 4)
            Spacer()
        }
        .frame(height: 18)
        .contentShape(Rectangle())
        .onTapGesture {
            onHaptic()
            withAnimation(.spring(response: 0.25, dampingFraction: 0.8)) {
                barMode = (barMode + 1) % 3
            }
        }
        .gesture(
            DragGesture(minimumDistance: 5)
                .onChanged { value in
                    dragOffset = value.translation.height
                }
                .onEnded { value in
                    let translation = value.translation.height
                    let velocity = value.predictedEndTranslation.height - translation

                    withAnimation(.spring(response: 0.25, dampingFraction: 0.8)) {
                        if translation < -20 || velocity < -40 {
                            // 위로 당김 -> 줄 수 증가
                            barMode = min(2, barMode + 1)
                        } else if translation > 20 || velocity > 40 {
                            // 아래로 밈 -> 줄 수 감소
                            barMode = max(0, barMode - 1)
                        }
                        dragOffset = 0
                    }
                    onHaptic()
                }
        )
    }
}

// MARK: - 2-Row Key Cluster (ㅗ Inverted-T Shape & Esc/Tab)
struct TwoRowKeyCluster: View {
    @ObservedObject var vm: TerminalViewModel

    var body: some View {
        HStack(alignment: .center) {
            // 왼쪽 조작부 (Esc / Tab)
            VStack(alignment: .leading, spacing: 4) {
                KeyButton(title: "Esc", width: 38, height: 25) {
                    vm.sendKey("\u{1b}")
                }
                KeyButton(title: "Tab", width: 46, height: 25) {
                    vm.sendKey("\t")
                }
            }

            Spacer()

            // 오른쪽 조작부 (Enter + ㅗ형 방향키 클러스터)
            VStack(alignment: .trailing, spacing: 4) {
                // Row 1: [Enter (44)] [ ↑ (30) ] [빈칸 (30)]
                HStack(spacing: 4) {
                    KeyButton(title: "Enter", width: 44, height: 25) {
                        vm.sendKey("\r")
                    }
                    KeyButton(title: "↑", width: 30, height: 25, fontSize: 13) {
                        vm.sendKey("\u{1b}[A")
                    }
                    Color.clear.frame(width: 30, height: 25)
                }

                // Row 2: [ ← (30) ] [ ↓ (30) ] [ → (30) ]
                HStack(spacing: 4) {
                    KeyButton(title: "←", width: 30, height: 25, fontSize: 13) {
                        vm.sendKey("\u{1b}[D")
                    }
                    KeyButton(title: "↓", width: 30, height: 25, fontSize: 13) {
                        vm.sendKey("\u{1b}[B")
                    }
                    KeyButton(title: "→", width: 30, height: 25, fontSize: 13) {
                        vm.sendKey("\u{1b}[C")
                    }
                }
            }
        }
    }
}

// MARK: - 1-Row Key Cluster (Compact)
struct SingleRowKeyCluster: View {
    @ObservedObject var vm: TerminalViewModel

    var body: some View {
        HStack {
            // 왼쪽: Esc, Tab
            HStack(spacing: 4) {
                KeyButton(title: "Esc", width: 38, height: 25) {
                    vm.sendKey("\u{1b}")
                }
                KeyButton(title: "Tab", width: 46, height: 25) {
                    vm.sendKey("\t")
                }
            }

            Spacer()

            // 오른쪽: Enter + 방향키 4개
            HStack(spacing: 4) {
                KeyButton(title: "Enter", width: 46, height: 25) {
                    vm.sendKey("\r")
                }
                KeyButton(title: "←", width: 30, height: 25, fontSize: 13) {
                    vm.sendKey("\u{1b}[D")
                }
                KeyButton(title: "↑", width: 30, height: 25, fontSize: 13) {
                    vm.sendKey("\u{1b}[A")
                }
                KeyButton(title: "↓", width: 30, height: 25, fontSize: 13) {
                    vm.sendKey("\u{1b}[B")
                }
                KeyButton(title: "→", width: 30, height: 25, fontSize: 13) {
                    vm.sendKey("\u{1b}[C")
                }
            }
        }
    }
}

// MARK: - Keycap Button Style
struct KeyButton: View {
    let title: String
    var width: CGFloat = 36
    var height: CGFloat = 25
    var fontSize: CGFloat = 11
    let action: () -> Void

    var body: some View {
        Button(action: action) {
            Text(title)
                .font(.system(size: fontSize, weight: .regular, design: .default))
                .foregroundColor(Color(white: 0.94))
                .frame(width: width, height: height)
                .background(
                    LinearGradient(
                        colors: [Color(white: 0.22), Color(white: 0.14)],
                        startPoint: .top,
                        endPoint: .bottom
                    )
                )
                .cornerRadius(5)
                .overlay(
                    RoundedRectangle(cornerRadius: 5)
                        .stroke(Color.white.opacity(0.12), lineWidth: 0.8)
                )
                .shadow(color: Color.black.opacity(0.4), radius: 2, x: 0, y: 1.5)
        }
        .buttonStyle(KeycapPressStyle())
    }
}

struct KeycapPressStyle: ButtonStyle {
    func makeBody(configuration: Configuration) -> some View {
        configuration.label
            .scaleEffect(configuration.isPressed ? 0.96 : 1.0)
            .opacity(configuration.isPressed ? 0.85 : 1.0)
            .offset(y: configuration.isPressed ? 1 : 0)
    }
}

// MARK: - Server Settings Modal
struct ServerSettingsView: View {
    @ObservedObject var vm: TerminalViewModel
    @Binding var isPresented: Bool
    @State private var tempURL: String = ""

    var body: some View {
        NavigationView {
            Form {
                Section(header: Text("서버 설정 (ttyd / Tailscale)")) {
                    TextField("http://100.107.195.21:7681", text: $tempURL)
                        .autocapitalization(.none)
                        .disableAutocorrection(true)
                        .keyboardType(.URL)
                }

                Section(header: Text("기본 접속 안내")) {
                    Text("Mac에서 실행 중인 ttyd-proxy(포트 7681)의 Tailscale IP 주소를 입력하세요.")
                        .font(.footnote)
                        .foregroundColor(.gray)
                }
            }
            .navigationTitle("터미널 서버 설정")
            .navigationBarTitleDisplayMode(.inline)
            .toolbar {
                ToolbarItem(placement: .cancellationAction) {
                    Button("취소") { isPresented = false }
                }
                ToolbarItem(placement: .confirmationAction) {
                    Button("저장") {
                        vm.serverURL = tempURL
                        vm.reload()
                        isPresented = false
                    }
                }
            }
            .onAppear {
                tempURL = vm.serverURL
            }
        }
    }
}

// MARK: - WKWebView Terminal Wrapper
struct TerminalWebView: UIViewRepresentable {
    let serverURL: String
    let reloadTrigger: UUID

    func makeCoordinator() -> Coordinator {
        Coordinator(self)
    }

    func makeUIView(context: Context) -> WKWebView {
        let config = WKWebViewConfiguration()
        config.allowsInlineMediaPlayback = true

        // 웹 전용 단축키 바(#agl-bar) 숨김 스크립트 주입 (네이티브 SwiftUI 컨트롤 사용)
        let hideWebBarJS = """
        var style = document.createElement('style');
        style.innerHTML = '#agl-bar { display: none !important; }';
        document.head.appendChild(style);
        """
        let script = WKUserScript(source: hideWebBarJS, injectionTime: .atDocumentEnd, forMainFrameOnly: true)
        config.userContentController.addUserScript(script)

        let webView = WKWebView(frame: .zero, configuration: config)
        webView.isOpaque = false
        webView.backgroundColor = UIColor(red: 0.13, green: 0.13, blue: 0.13, alpha: 1.0)
        webView.scrollView.backgroundColor = webView.backgroundColor
        webView.scrollView.bounces = false
        webView.navigationDelegate = context.coordinator

        loadURL(in: webView)
        return webView
    }

    func updateUIView(_ webView: WKWebView, context: Context) {
        if context.coordinator.lastReloadTrigger != reloadTrigger {
            context.coordinator.lastReloadTrigger = reloadTrigger
            loadURL(in: webView)
        }
    }

    private func loadURL(in webView: WKWebView) {
        guard let url = URL(string: serverURL) else { return }
        let request = URLRequest(url: url, cachePolicy: .reloadIgnoringLocalCacheData, timeoutInterval: 10)
        webView.load(request)
    }

    class Coordinator: NSObject, WKNavigationDelegate {
        var parent: TerminalWebView
        var lastReloadTrigger: UUID

        init(_ parent: TerminalWebView) {
            self.parent = parent
            self.lastReloadTrigger = parent.reloadTrigger
        }

        func webView(_ webView: WKWebView, didFinish navigation: WKNavigation!) {
            // 페이지 로드 완료 시 #agl-bar 다시 한번 숨김 보장
            let js = "var b = document.getElementById('agl-bar'); if(b) b.style.display = 'none';"
            webView.evaluateJavaScript(js, completionHandler: nil)
        }
    }
}
