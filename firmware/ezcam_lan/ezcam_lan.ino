// ESP32-CAM 區網拍照韌體（AI-Thinker ESP32-CAM 板）
//
// 開機後連上 Wi-Fi，在區網提供：
//   http://ezcam.local/          網頁預覽（按鈕拍照）
//   http://ezcam.local/capture   拍一張新照片，回傳 JPEG
//   http://ezcam.local/status    狀態 JSON
// 看不到 ezcam.local 時，改用序列埠監控視窗印出的 IP，例如 http://192.168.1.50/capture
//
// 只要改下面「要改的設定」三行，其他不用動。

#include <WiFi.h>
#include <WebServer.h>
#include <ESPmDNS.h>
#include "esp_camera.h"

// ===== 要改的設定 =====
const char *WIFI_SSID = "你的WiFi名稱";
const char *WIFI_PASS = "你的WiFi密碼";
const char *CAM_KEY   = "";   // 空字串＝不檢查；有填的話，網址要加 ?key=這串
// =====================

const char *HOSTNAME = "ezcam";   // 區網名稱：ezcam.local
const int FLASH_LED = 4;          // 板子上的白色補光燈
const bool USE_FLASH = false;     // 光線太暗再改成 true

// AI-Thinker ESP32-CAM 腳位
#define PWDN_GPIO_NUM 32
#define RESET_GPIO_NUM -1
#define XCLK_GPIO_NUM 0
#define SIOD_GPIO_NUM 26
#define SIOC_GPIO_NUM 27
#define Y9_GPIO_NUM 35
#define Y8_GPIO_NUM 34
#define Y7_GPIO_NUM 39
#define Y6_GPIO_NUM 36
#define Y5_GPIO_NUM 21
#define Y4_GPIO_NUM 19
#define Y3_GPIO_NUM 18
#define Y2_GPIO_NUM 5
#define VSYNC_GPIO_NUM 25
#define HREF_GPIO_NUM 23
#define PCLK_GPIO_NUM 22

WebServer server(80);
unsigned long shots = 0;

bool keyOk() {
  if (CAM_KEY[0] == '\0') return true;
  if (server.arg("key") == CAM_KEY) return true;
  server.send(401, "application/json", "{\"error\":\"bad key\"}");
  return false;
}

bool startCamera() {
  camera_config_t c = {};
  c.ledc_channel = LEDC_CHANNEL_0;
  c.ledc_timer = LEDC_TIMER_0;
  c.pin_d0 = Y2_GPIO_NUM; c.pin_d1 = Y3_GPIO_NUM; c.pin_d2 = Y4_GPIO_NUM; c.pin_d3 = Y5_GPIO_NUM;
  c.pin_d4 = Y6_GPIO_NUM; c.pin_d5 = Y7_GPIO_NUM; c.pin_d6 = Y8_GPIO_NUM; c.pin_d7 = Y9_GPIO_NUM;
  c.pin_xclk = XCLK_GPIO_NUM; c.pin_pclk = PCLK_GPIO_NUM;
  c.pin_vsync = VSYNC_GPIO_NUM; c.pin_href = HREF_GPIO_NUM;
  c.pin_sccb_sda = SIOD_GPIO_NUM; c.pin_sccb_scl = SIOC_GPIO_NUM;
  c.pin_pwdn = PWDN_GPIO_NUM; c.pin_reset = RESET_GPIO_NUM;
  c.xclk_freq_hz = 20000000;
  c.pixel_format = PIXFORMAT_JPEG;
  c.grab_mode = CAMERA_GRAB_LATEST;   // 永遠拿最新的一張，不拿舊畫面
  if (psramFound()) {
    c.frame_size = FRAMESIZE_SVGA;    // 800x600，清楚又不會太大
    c.jpeg_quality = 12;
    c.fb_count = 2;
    c.fb_location = CAMERA_FB_IN_PSRAM;
  } else {
    c.frame_size = FRAMESIZE_VGA;
    c.jpeg_quality = 14;
    c.fb_count = 1;
    c.fb_location = CAMERA_FB_IN_DRAM;
  }
  esp_err_t err = esp_camera_init(&c);
  if (err != ESP_OK) {
    Serial.printf("相機啟動失敗 0x%x，請檢查排線\n", err);
    return false;
  }
  return true;
}

void handleCapture() {
  if (!keyOk()) return;
  if (USE_FLASH) { digitalWrite(FLASH_LED, HIGH); delay(150); }
  // 丟掉一張緩衝，確保拿到「現在」的畫面
  camera_fb_t *fb = esp_camera_fb_get();
  if (fb) esp_camera_fb_return(fb);
  fb = esp_camera_fb_get();
  if (USE_FLASH) digitalWrite(FLASH_LED, LOW);
  if (!fb) {
    server.send(503, "application/json", "{\"error\":\"capture failed\"}");
    return;
  }
  shots++;
  size_t len = fb->len;
  server.sendHeader("Cache-Control", "no-store");
  server.setContentLength(len);
  server.send(200, "image/jpeg", "");
  server.client().write(fb->buf, len);
  esp_camera_fb_return(fb);
  Serial.printf("拍照 #%lu，%u bytes\n", shots, (unsigned)len);
}

void handleStatus() {
  if (!keyOk()) return;
  String s = "{\"ok\":true,\"ip\":\"" + WiFi.localIP().toString() +
             "\",\"rssi\":" + String(WiFi.RSSI()) +
             ",\"shots\":" + String(shots) +
             ",\"uptime_s\":" + String(millis() / 1000) + "}";
  server.send(200, "application/json", s);
}

void handleRoot() {
  String q = CAM_KEY[0] ? String("?key=") + CAM_KEY : String("");
  String sep = CAM_KEY[0] ? "&" : "?";
  String html =
    "<!doctype html><meta charset=utf-8><meta name=viewport content='width=device-width'>"
    "<title>EZ-CAM</title><body style='font-family:sans-serif;text-align:center'>"
    "<h2>EZ-CAM 區網相機</h2>"
    "<p><button onclick=\"document.getElementById('p').src='/capture" + q + sep + "t='+Date.now()\" "
    "style='font-size:20px;padding:8px 24px'>拍照</button></p>"
    "<img id=p style='max-width:100%' src='/capture" + q + "'>";
  server.send(200, "text/html; charset=utf-8", html);
}

void setup() {
  Serial.begin(115200);
  pinMode(FLASH_LED, OUTPUT);
  digitalWrite(FLASH_LED, LOW);

  if (!startCamera()) { delay(3000); ESP.restart(); }

  WiFi.mode(WIFI_STA);
  WiFi.setSleep(false);           // 關省電，拍照回應比較快
  WiFi.setHostname(HOSTNAME);
  WiFi.begin(WIFI_SSID, WIFI_PASS);
  Serial.print("連線 Wi-Fi ");
  Serial.print(WIFI_SSID);
  for (int i = 0; WiFi.status() != WL_CONNECTED; i++) {
    delay(500);
    Serial.print(".");
    if (i > 60) { Serial.println("\n連不上，重開機再試"); ESP.restart(); }
  }
  Serial.println();
  Serial.print("連上了！相機網址： http://");
  Serial.print(WiFi.localIP());
  Serial.println("/capture");

  if (MDNS.begin(HOSTNAME)) {
    MDNS.addService("http", "tcp", 80);
    Serial.println("也可以用： http://ezcam.local/capture");
  }

  server.on("/", handleRoot);
  server.on("/capture", handleCapture);
  server.on("/status", handleStatus);
  server.begin();
}

void loop() {
  server.handleClient();
  if (WiFi.status() != WL_CONNECTED) {   // 斷線自動重連
    static unsigned long last = 0;
    if (millis() - last > 10000) { last = millis(); WiFi.reconnect(); }
  }
}
