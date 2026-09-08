import React, { useState, useEffect } from 'react';
import { Dialog, Input, Button, Tag, Loading, Space, MessagePlugin } from 'tdesign-react';
import { SearchIcon, CloseIcon, FileIcon, ServerIcon } from 'tdesign-icons-react';

interface SearchResult {
  document: {
    id: string;
    kbId: string;
    title: string;
    content: string;
    category: string;
    tags: string[];
    status: string;
  };
  similarity: number;
  searchType: string;
  matchedContent: string;
  highlightedContent: string;
  chunkIndex?: number; // 向量块索引
}

interface SearchModalProps {
  isOpen: boolean;
  onClose: () => void;
  kbId?: string; // 如果提供，则在知识库内搜索；否则全局搜索
  kbName?: string;
  onResultClick?: (result: SearchResult) => void;
}

const SearchModal: React.FC<SearchModalProps> = ({
  isOpen,
  onClose,
  kbId,
  kbName,
  onResultClick
}) => {
  const [query, setQuery] = useState('');
  const [results, setResults] = useState<SearchResult[]>([]);
  const [loading, setLoading] = useState(false);
  const [searchType, setSearchType] = useState<'hybrid' | 'vector' | 'sql'>('hybrid');
  const [hasSearched, setHasSearched] = useState(false);
  const [similarityThreshold, setSimilarityThreshold] = useState(0.3); // 降低默认相似度阈值

  useEffect(() => {
    if (!isOpen) {
      setQuery('');
      setResults([]);
      setHasSearched(false);
    }
  }, [isOpen]);

  const handleSearch = async () => {
    if (!query.trim()) return;

    setLoading(true);
    setHasSearched(true);

    try {
      const API_BASE_URL = 'http://localhost:5000/api';
      const token = localStorage.getItem('authToken');
      
      const endpoint = kbId 
        ? `${API_BASE_URL}/kb/${kbId}/search`
        : `${API_BASE_URL}/kb/search`;

      const response = await fetch(endpoint, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          'Authorization': `Bearer ${token}`
        },
        body: JSON.stringify({
          query: query.trim(),
          searchType,
          highlight: true,
          similarityThreshold: similarityThreshold // 添加相似度阈值参数
          // 不指定limit，让后端使用知识库设置中的默认值
        })
      });

      if (!response.ok) {
        throw new Error('搜索失败');
      }

      const data = await response.json();
      
      if (data.success && data.data) {
        setResults(data.data.results || []);
      }
    } catch (error) {
      console.error('搜索失败:', error);
      setResults([]);
    } finally {
      setLoading(false);
    }
  };

  const handleKeyPress = (e: React.KeyboardEvent) => {
    if (e.key === 'Enter') {
      handleSearch();
    }
  };

  const handleResultClick = (result: SearchResult) => {
    if (onResultClick) {
      onResultClick(result);
    }
    onClose();
  };

  const getSearchTypeBadge = (type: string) => {
    const badges = {
      vector: { color: 'bg-purple-100 text-purple-800', text: '向量' },
      sql: { color: 'bg-blue-100 text-blue-800', text: 'SQL' },
      hybrid: { color: 'bg-green-100 text-green-800', text: '混合' }
    };
    return badges[type as keyof typeof badges] || badges.hybrid;
  };

  return (
    <Dialog
      header={
        <div style={{ display: 'flex', alignItems: 'center' }}>
          <SearchIcon style={{ color: '#3b82f6', marginRight: 8 }} />
          <span>{kbId ? `在 "${kbName}" 中搜索` : '全局搜索'}</span>
        </div>
      }
      visible={isOpen}
      onClose={onClose}
      footer={null}
      width={700}
    >
      {/* 搜索输入 */}
      <div style={{ marginBottom: 16 }}>
        <div style={{ display: 'flex', gap: 8, marginBottom: 12 }}>
          <div style={{ flex: 1, position: 'relative' }}>
            <Input
              value={query}
              onChange={(val) => setQuery(val as string)}
              placeholder="输入搜索关键词..."
              prefixIcon={<SearchIcon />}
              onEnter={handleSearch}
              clearable
            />
          </div>
          <Button
            theme="primary"
            onClick={handleSearch}
            loading={loading}
            disabled={!query.trim()}
          >
            搜索
          </Button>
        </div>

        {/* 搜索类型选择 */}
        <div style={{ display: 'flex', gap: 8, marginBottom: 12 }}>
          <Button
            theme={searchType === 'hybrid' ? 'primary' : 'default'}
            onClick={() => setSearchType('hybrid')}
          >
            混合搜索
          </Button>
          <Button
            theme={searchType === 'vector' ? 'primary' : 'default'}
            onClick={() => setSearchType('vector')}
          >
            向量搜索
          </Button>
          <Button
            theme={searchType === 'sql' ? 'primary' : 'default'}
            onClick={() => setSearchType('sql')}
          >
            关键词搜索
          </Button>
        </div>

        {/* 相似度阈值滑块 - 仅在向量搜索或混合搜索时显示 */}
        {(searchType === 'vector' || searchType === 'hybrid') && (
          <div>
            <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: 4 }}>
              <span style={{ fontSize: 14, color: '#666' }}>相似度阈值</span>
              <span style={{ fontSize: 14, color: '#333', fontWeight: 500 }}>{similarityThreshold.toFixed(2)}</span>
            </div>
            <input
              type="range"
              min="0.1"
              max="1.0"
              step="0.05"
              value={similarityThreshold}
              onChange={(e) => setSimilarityThreshold(parseFloat(e.target.value))}
              style={{ width: '100%' }}
            />
            <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: 12, color: '#999' }}>
              <span>更宽松</span>
              <span>更严格</span>
            </div>
          </div>
        )}
      </div>

      {/* 搜索结果 */}
      <div style={{ maxHeight: 400, overflowY: 'auto' }}>
        {loading ? (
          <div style={{ textAlign: 'center', padding: 48 }}>
            <Loading />
            <p style={{ marginTop: 16, color: '#666' }}>搜索中...</p>
          </div>
        ) : hasSearched ? (
          results.length > 0 ? (
            <div style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>
              {results.map((result, index) => {
                const badge = getSearchTypeBadge(result.searchType);
                return (
                  <div
                    key={index}
                    onClick={() => handleResultClick(result)}
                    style={{
                      padding: 16,
                      border: '1px solid #e5e5e5',
                      borderRadius: 8,
                      cursor: 'pointer',
                      transition: 'all 0.2s'
                    }}
                  >
                    <div style={{ display: 'flex', alignItems: 'flex-start', justifyContent: 'space-between', marginBottom: 8 }}>
                      <div style={{ display: 'flex', alignItems: 'center', flex: 1 }}>
                        <FileIcon style={{ color: '#3b82f6', marginRight: 8, flexShrink: 0 }} />
                        <h3 style={{ fontWeight: 500, color: '#333', margin: 0, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                          {result.document.title}
                        </h3>
                      </div>
                      <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginLeft: 8 }}>
                        <Tag theme={badge.theme}>{badge.text}</Tag>
                        <span style={{ fontSize: 12, color: '#999' }}>
                          {(result.similarity * 100).toFixed(0)}%
                        </span>
                        {result.searchType === 'vector' && result.chunkIndex !== undefined && (
                          <span style={{ fontSize: 12, color: '#999' }}>
                            文本块 {result.chunkIndex + 1}
                          </span>
                        )}
                      </div>
                    </div>

                    {result.document.category && (
                      <div style={{ marginBottom: 8 }}>
                        <Tag theme="primary">{result.document.category}</Tag>
                      </div>
                    )}

                    <div
                      style={{ fontSize: 14, color: '#666', lineHeight: 1.5 }}
                      dangerouslySetInnerHTML={{
                        __html: result.highlightedContent || result.matchedContent
                      }}
                    />

                    {result.document.tags && result.document.tags.length > 0 && (
                      <div style={{ display: 'flex', flexWrap: 'wrap', gap: 4, marginTop: 8 }}>
                        {result.document.tags.map((tag, tagIndex) => (
                          <Tag key={tagIndex} theme="default">{tag}</Tag>
                        ))}
                      </div>
                    )}
                  </div>
                );
              })}
            </div>
          ) : (
            <div style={{ textAlign: 'center', padding: 48 }}>
              <ServerIcon style={{ fontSize: 48, color: '#ccc' }} />
              <p style={{ marginTop: 16, color: '#666' }}>未找到匹配的结果</p>
              <p style={{ fontSize: 14, color: '#999', marginTop: 4 }}>
                尝试使用不同的关键词或搜索类型
              </p>
            </div>
          )
        ) : (
          <div style={{ textAlign: 'center', padding: 48 }}>
            <SearchIcon style={{ fontSize: 48, color: '#ccc' }} />
            <p style={{ marginTop: 16, color: '#666' }}>输入关键词开始搜索</p>
            <p style={{ fontSize: 14, color: '#999', marginTop: 4 }}>
              支持向量搜索、关键词搜索和混合搜索
            </p>
          </div>
        )}
      </div>
    </Dialog>
  );
};

export default SearchModal;
