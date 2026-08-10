import { useEffect, useRef, useState, useCallback } from 'react';
import { MapPin } from 'lucide-react';

interface LocationInputProps {
  value: string;
  onChange: (value: string) => void;
  className?: string;
}

declare global {
  interface Window {
    google: typeof google;
    initGoogleMapsCallback: () => void;
  }
}

type PlaceSelectionEvent = Event & {
  place?: { formattedAddress?: string };
};

type ModernAutocompleteElement = HTMLElement & {
  addEventListener(
    type: 'gmp-placeselect',
    listener: (event: PlaceSelectionEvent) => void,
  ): void;
};

type AutocompleteHandle =
  | google.maps.places.Autocomplete
  | ModernAutocompleteElement;

const LocationInput = ({ value, onChange, className }: LocationInputProps) => {
  const inputRef = useRef<HTMLInputElement>(null);
  const autocompleteElementRef = useRef<AutocompleteHandle | null>(null);
  const [isApiLoaded, setIsApiLoaded] = useState(false);
  const onChangeRef = useRef(onChange);
  const isInitializedRef = useRef(false);

  // onChange 变化时同步引用
  useEffect(() => {
    onChangeRef.current = onChange;
  }, [onChange]);

  // 加载 Google 地图 API
  useEffect(() => {
    const loadGoogleMapsScript = (): Promise<void> => {
      return new Promise((resolve, reject) => {
        // 检查 API Key
        const apiKey = import.meta.env.VITE_GOOGLE_MAPS_API_KEY;
        if (!apiKey) {
          console.warn('未配置 Google 地图 API Key，已禁用地点自动补全。');
          reject(new Error('未配置 Google 地图 API Key'));
          return;
        }

        // 检查 API 是否已经加载
        if (window.google?.maps?.places) {
          resolve();
          return;
        }

        // 检查脚本是否正在加载
        if (document.querySelector('script[src*="maps.googleapis.com"]')) {
          const checkLoaded = setInterval(() => {
            if (window.google?.maps?.places) {
              clearInterval(checkLoaded);
              resolve();
            }
          }, 100);
          setTimeout(() => {
            clearInterval(checkLoaded);
            reject(new Error('加载 Google 地图超时'));
          }, 10000);
          return;
        }

        // 创建加载完成回调
        window.initGoogleMapsCallback = () => {
          resolve();
        };

        // 加载脚本
        const script = document.createElement('script');
        script.src = `https://maps.googleapis.com/maps/api/js?key=${apiKey}&libraries=places&callback=initGoogleMapsCallback`;
        script.async = true;
        script.defer = true;
        script.onerror = () => reject(new Error('Google 地图脚本加载失败'));
        document.head.appendChild(script);
      });
    };

    const loadApi = async () => {
      try {
        await loadGoogleMapsScript();
        setIsApiLoaded(true);
      } catch (error) {
        console.warn('Google 地图自动补全不可用：', error instanceof Error ? error.message : '未知错误');
        // 降级为普通文本框
        if (inputRef.current) {
          inputRef.current.style.display = '';
        }
      }
    };

    loadApi();
  }, []);

  // API 加载完成且输入框可用时初始化自动补全
  useEffect(() => {
    if (!isApiLoaded || !inputRef.current || !window.google?.maps?.places || isInitializedRef.current) {
      return;
    }

    try {
      // 优先使用新版组件，并兼容旧版自动补全 API
      if (window.google.maps.places.PlaceAutocompleteElement) {
        // 创建并配置新版 PlaceAutocompleteElement
        const autocompleteElement = document.createElement(
          'gmp-place-autocomplete',
        ) as ModernAutocompleteElement;
        autocompleteElement.setAttribute('type', 'cities');

        // 用自动补全组件替换输入框
        const parentElement = inputRef.current.parentElement;
        if (parentElement) {
          parentElement.insertBefore(autocompleteElement, inputRef.current);
          inputRef.current.style.display = 'none';

          // 让自动补全组件样式与输入框一致
          autocompleteElement.style.width = '100%';
          autocompleteElement.style.height = '100%';

          // 监听地点选择
          autocompleteElement.addEventListener('gmp-placeselect', (event) => {
            const place = event.place;
            if (place?.formattedAddress) {
              onChangeRef.current(place.formattedAddress);
            }
          });

          autocompleteElementRef.current = autocompleteElement;
        }
      } else {
        // 回退到旧版自动补全 API
        console.warn('正在使用已弃用的 Google 地图自动补全 API，建议升级到 PlaceAutocompleteElement。');

        autocompleteElementRef.current = new window.google.maps.places.Autocomplete(inputRef.current, {
          types: ['(cities)'],
        });

        // 监听 place_changed 事件
        const autocomplete = autocompleteElementRef.current;
        if (autocomplete) {
          autocomplete.addListener('place_changed', () => {
            const place = autocomplete.getPlace();
            if (place?.formatted_address) {
              onChangeRef.current(place.formatted_address);
            }
          });
        }
      }

      // 设置自动补全下拉框样式
      const style = document.createElement('style');
      style.textContent = `
        .pac-container {
          background-color: white !important;
          border: 1px solid rgba(70, 139, 255, 0.1) !important;
          border-radius: 0.75rem !important;
          margin-top: 0.5rem !important;
          font-family: "Noto Sans", sans-serif !important;
          overflow: hidden !important;
          box-shadow: none !important;
        }
        .pac-item {
          padding: 0.875rem 1.25rem !important;
          cursor: pointer !important;
          transition: all 0.2s ease-in-out !important;
          border-bottom: 1px solid rgba(70, 139, 255, 0.05) !important;
        }
        .pac-item:last-child {
          border-bottom: none !important;
        }
        .pac-item:hover {
          background-color: rgba(70, 139, 255, 0.03) !important;
        }
        .pac-item-selected {
          background-color: rgba(70, 139, 255, 0.05) !important;
        }
        .pac-item-query {
          color: #1a365d !important;
          font-size: 0.9375rem !important;
          font-weight: 500 !important;
        }
        .pac-matched {
          font-weight: 600 !important;
        }
        .pac-item span:not(.pac-item-query) {
          color: #64748b !important;
          font-size: 0.8125rem !important;
          margin-left: 0.5rem !important;
        }
        /* 隐藏地点图标 */
        .pac-icon {
          display: none !important;
        }
        /* 设置新版 PlaceAutocompleteElement 样式 */
        gmp-place-autocomplete {
          width: 100% !important;
          --gmp-place-autocomplete-font-family: "DM Sans", sans-serif !important;
        }
      `;
      document.head.appendChild(style);

      isInitializedRef.current = true;
    } catch (error) {
      console.error('初始化 Google 地图自动补全失败：', error);
    }

    const inputElement = inputRef.current;

    // 清理自动补全资源
    return () => {
      if (autocompleteElementRef.current) {
        if (window.google?.maps?.event && typeof autocompleteElementRef.current.addListener === 'function') {
          // 清理旧版自动补全组件
          window.google.maps.event.clearInstanceListeners(autocompleteElementRef.current);
        } else if (autocompleteElementRef.current.remove) {
          // 清理新版自动补全组件
          autocompleteElementRef.current.remove();
          if (inputElement) {
            inputElement.style.display = '';
          }
        }
        autocompleteElementRef.current = null;
        isInitializedRef.current = false;
      }
    };
  }, [isApiLoaded]); // 通过引用读取 onChange，无需加入依赖项

  // 处理手工输入
  const handleInputChange = useCallback((e: React.ChangeEvent<HTMLInputElement>) => {
    onChange(e.target.value);
  }, [onChange]);

  return (
    <div className="relative group">
      <div className="absolute inset-0 bg-gradient-to-r from-gray-50/0 via-gray-100/50 to-gray-50/0 opacity-0 group-hover:opacity-100 transition-opacity duration-500 rounded-lg"></div>
      <MapPin className="absolute left-4 top-1/2 -translate-y-1/2 h-5 w-5 stroke-[#468BFF] transition-all duration-200 group-hover:stroke-[#8FBCFA] z-10" strokeWidth={1.5} />
      <input
        ref={inputRef}
        type="text"
        value={value}
        onChange={handleInputChange}
        onKeyDown={(e) => {
          if (e.key === 'Enter') {
            e.preventDefault();
          }
        }}
        className={`${className} !font-['DM_Sans']`}
        placeholder="城市,国家(如「深圳」)"
      />
    </div>
  );
};

export default LocationInput;
