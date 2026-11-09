package com.barrarun.game;

import android.annotation.SuppressLint;
import android.os.Bundle;
import android.view.View;
import android.view.WindowManager;
import android.webkit.WebResourceRequest;
import android.webkit.WebResourceResponse;
import android.webkit.WebSettings;
import android.webkit.WebView;
import android.webkit.WebViewClient;

import androidx.appcompat.app.AppCompatActivity;
import androidx.webkit.WebViewAssetLoader;

import java.io.ByteArrayInputStream;
import java.io.InputStream;
import java.util.HashMap;
import java.util.Map;

/**
 * Hosts the Barra Run HTML/Three.js game via WebViewAssetLoader so fetch()
 * of relative assets/ works (https://appassets.androidplatform.net origin).
 */
public class MainActivity extends AppCompatActivity {

    private WebView webView;

    @SuppressLint("SetJavaScriptEnabled")
    @Override
    protected void onCreate(Bundle savedInstanceState) {
        super.onCreate(savedInstanceState);
        getWindow().addFlags(WindowManager.LayoutParams.FLAG_KEEP_SCREEN_ON);

        webView = new WebView(this);
        setContentView(webView);

        final WebViewAssetLoader assetLoader = new WebViewAssetLoader.Builder()
                .addPathHandler("/assets/", new MimeFixingAssetsPathHandler(
                        new WebViewAssetLoader.AssetsPathHandler(this)))
                .build();

        WebSettings settings = webView.getSettings();
        settings.setJavaScriptEnabled(true);
        settings.setDomStorageEnabled(true);
        settings.setAllowFileAccess(false);
        settings.setAllowContentAccess(false);
        settings.setMediaPlaybackRequiresUserGesture(false);
        settings.setCacheMode(WebSettings.LOAD_DEFAULT);
        settings.setOffscreenPreRaster(true);

        webView.setLayerType(View.LAYER_TYPE_HARDWARE, null);

        webView.setWebViewClient(new WebViewClient() {
            @Override
            public WebResourceResponse shouldInterceptRequest(WebView view, WebResourceRequest request) {
                return assetLoader.shouldInterceptRequest(request.getUrl());
            }
        });

        webView.loadUrl("https://appassets.androidplatform.net/assets/index.html");
    }

    /**
     * Ensures .js / .mjs responses use text/javascript so ES modules load.
     * Some WebView/AssetLoader combos return empty or application/octet-stream.
     */
    private static final class MimeFixingAssetsPathHandler implements WebViewAssetLoader.PathHandler {
        private final WebViewAssetLoader.PathHandler delegate;

        MimeFixingAssetsPathHandler(WebViewAssetLoader.PathHandler delegate) {
            this.delegate = delegate;
        }

        @Override
        public WebResourceResponse handle(String path) {
            WebResourceResponse resp = delegate.handle(path);
            if (resp == null) return null;

            String lower = path == null ? "" : path.toLowerCase();
            String mime = resp.getMimeType();
            boolean isJs = lower.endsWith(".js") || lower.endsWith(".mjs");
            boolean badMime = mime == null || mime.isEmpty()
                    || "application/octet-stream".equalsIgnoreCase(mime)
                    || "text/plain".equalsIgnoreCase(mime);

            if (isJs && badMime) {
                InputStream data = resp.getData();
                if (data == null) {
                    data = new ByteArrayInputStream(new byte[0]);
                }
                Map<String, String> headers = resp.getResponseHeaders();
                if (headers == null) headers = new HashMap<>();
                else headers = new HashMap<>(headers);
                headers.put("Access-Control-Allow-Origin", "*");
                return new WebResourceResponse(
                        "text/javascript",
                        resp.getEncoding() != null ? resp.getEncoding() : "UTF-8",
                        resp.getStatusCode() > 0 ? resp.getStatusCode() : 200,
                        resp.getReasonPhrase() != null && !resp.getReasonPhrase().isEmpty()
                                ? resp.getReasonPhrase() : "OK",
                        headers,
                        data
                );
            }

            // Also ensure .json is application/json when missing
            if (lower.endsWith(".json") && badMime) {
                Map<String, String> headers = resp.getResponseHeaders();
                if (headers == null) headers = new HashMap<>();
                else headers = new HashMap<>(headers);
                return new WebResourceResponse(
                        "application/json",
                        resp.getEncoding() != null ? resp.getEncoding() : "UTF-8",
                        resp.getStatusCode() > 0 ? resp.getStatusCode() : 200,
                        resp.getReasonPhrase() != null && !resp.getReasonPhrase().isEmpty()
                                ? resp.getReasonPhrase() : "OK",
                        headers,
                        resp.getData() != null ? resp.getData() : new ByteArrayInputStream(new byte[0])
                );
            }

            return resp;
        }
    }

    @Override
    public void onBackPressed() {
        if (webView != null && webView.canGoBack()) {
            webView.goBack();
        } else {
            super.onBackPressed();
        }
    }

    @Override
    protected void onResume() {
        super.onResume();
        if (webView != null) {
            webView.onResume();
        }
    }

    @Override
    protected void onPause() {
        if (webView != null) {
            webView.onPause();
        }
        super.onPause();
    }

    @Override
    protected void onDestroy() {
        if (webView != null) {
            webView.destroy();
            webView = null;
        }
        super.onDestroy();
    }
}
