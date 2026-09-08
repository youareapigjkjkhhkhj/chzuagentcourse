import React from 'react';
import { Dialog, Input, Select, Button, Radio, Tag, Upload, Progress, Space } from 'tdesign-react';
import { CloseIcon, UploadIcon, LoadingIcon } from 'tdesign-icons-react';

interface FormData {
  title: string;
  content: string;
  category: string;
  tags: string[];
  status: 'draft' | 'published';
}

interface DocumentModalProps {
  isOpen: boolean;
  onClose: () => void;
  onSubmit: () => void;
  formData: FormData;
  setFormData: React.Dispatch<React.SetStateAction<FormData>>;
  tagInput: string;
  setTagInput: React.Dispatch<React.SetStateAction<string>>;
  onAddTag: () => void;
  onRemoveTag: (tag: string) => void;
  categories: string[];
  title: string;
  loading?: boolean;
}

export const DocumentModal: React.FC<DocumentModalProps> = ({
  isOpen,
  onClose,
  onSubmit,
  formData,
  setFormData,
  tagInput,
  setTagInput,
  onAddTag,
  onRemoveTag,
  categories,
  title,
  loading
}) => {
  return (
    <Dialog
      header={title}
      visible={isOpen}
      onClose={onClose}
      footer={
        <div style={{ display: 'flex', justifyContent: 'flex-end', gap: 8 }}>
          <Button theme="default" onClick={onClose}>取消</Button>
          <Button 
            theme="primary" 
            onClick={onSubmit}
            loading={loading}
          >
            保存
          </Button>
        </div>
      }
    >
      <div style={{ display: 'flex', flexDirection: 'column', gap: 16 }}>
        <div>
          <div style={{ marginBottom: 8, fontSize: 14, fontWeight: 500 }}>
            标题 <span style={{ color: '#f56c6c' }}>*</span>
          </div>
          <Input
            value={formData.title}
            onChange={(val) => setFormData(prev => ({ ...prev, title: val as string }))}
            placeholder="请输入标题"
          />
        </div>

        <div>
          <div style={{ marginBottom: 8, fontSize: 14, fontWeight: 500 }}>分类</div>
          <Select
            value={formData.category}
            onChange={(val) => setFormData(prev => ({ ...prev, category: val as string }))}
            options={categories.filter(c => c !== '全部').map(c => ({ label: c, value: c }))}
            placeholder="选择分类"
            clearable
          />
        </div>

        <div>
          <div style={{ marginBottom: 8, fontSize: 14, fontWeight: 500 }}>
            内容 <span style={{ color: '#f56c6c' }}>*</span>
          </div>
          <textarea
            value={formData.content}
            onChange={(e) => setFormData(prev => ({ ...prev, content: e.target.value }))}
            rows={8}
            style={{ width: '100%', padding: '8px 12px', border: '1px solid #dcdfe6', borderRadius: 4, resize: 'vertical' }}
            required
          />
        </div>

        <div>
          <div style={{ marginBottom: 8, fontSize: 14, fontWeight: 500 }}>标签</div>
          <div style={{ display: 'flex', gap: 8, marginBottom: 8 }}>
            <Input
              value={tagInput}
              onChange={(val) => setTagInput(val as string)}
              placeholder="输入标签后按回车添加"
              onEnter={onAddTag}
              style={{ flex: 1 }}
            />
            <Button theme="primary" onClick={onAddTag}>添加</Button>
          </div>
          <div style={{ display: 'flex', flexWrap: 'wrap', gap: 8 }}>
            {formData.tags.map((tag, index) => (
              <Tag
                key={index}
                closable
                onClose={() => onRemoveTag(tag)}
              >
                {tag}
              </Tag>
            ))}
          </div>
        </div>

        <div>
          <div style={{ marginBottom: 8, fontSize: 14, fontWeight: 500 }}>状态</div>
          <Radio.Group
            value={formData.status}
            onChange={(val) => setFormData(prev => ({ ...prev, status: val as 'draft' | 'published' }))}
            options={[
              { label: '草稿', value: 'draft' },
              { label: '发布', value: 'published' }
            ]}
          />
        </div>
      </div>
    </Dialog>
  );
};

interface FileUploadModalProps {
  isOpen: boolean;
  onClose: () => void;
  onSubmit: () => void;
  file: File | null;
  setFile: React.Dispatch<React.SetStateAction<File | null>>;
  formData: FormData;
  setFormData: React.Dispatch<React.SetStateAction<FormData>>;
  tagInput: string;
  setTagInput: React.Dispatch<React.SetStateAction<string>>;
  onAddTag: () => void;
  onRemoveTag: (tag: string) => void;
  categories: string[];
  uploading?: boolean;
  uploadProgress?: number;
  title: string;
  acceptedFormats?: string;
}

export const FileUploadModal: React.FC<FileUploadModalProps> = ({
  isOpen,
  onClose,
  onSubmit,
  file,
  setFile,
  formData,
  setFormData,
  tagInput,
  setTagInput,
  onAddTag,
  onRemoveTag,
  categories,
  uploading,
  uploadProgress,
  title,
  acceptedFormats = '.txt,.md,.pdf,.docx,.xlsx,.pptx'
}) => {
  return (
    <Dialog
      header={title}
      visible={isOpen}
      onClose={onClose}
      footer={
        <div style={{ display: 'flex', justifyContent: 'flex-end', gap: 8 }}>
          <Button theme="default" onClick={onClose} disabled={uploading}>取消</Button>
          <Button 
            theme="primary" 
            onClick={onSubmit}
            loading={uploading}
            disabled={!file}
          >
            上传
          </Button>
        </div>
      }
    >
      <div style={{ display: 'flex', flexDirection: 'column', gap: 16 }}>
        <div>
          <div style={{ marginBottom: 8, fontSize: 14, fontWeight: 500 }}>
            文档标题 <span style={{ color: '#f56c6c' }}>*</span>
          </div>
          <Input
            value={formData.title}
            onChange={(val) => setFormData(prev => ({ ...prev, title: val as string }))}
            placeholder="输入文档标题"
          />
        </div>

        <div>
          <div style={{ marginBottom: 8, fontSize: 14, fontWeight: 500 }}>
            选择文件 <span style={{ color: '#f56c6c' }}>*</span>
          </div>
          <Upload
            action=""
            accept={acceptedFormats}
            onChange={(file) => {
              if (file && file.length > 0) {
                const selectedFile = file[0].raw;
                setFile(selectedFile);
                if (!formData.title.trim()) {
                  let fileNameWithoutExt = selectedFile.name;
                  if (fileNameWithoutExt.endsWith('.tar.gz')) {
                    fileNameWithoutExt = fileNameWithoutExt.slice(0, -7);
                  } else {
                    fileNameWithoutExt = fileNameWithoutExt.replace(/\.[^/.]+$/, "");
                  }
                  setFormData(prev => ({ ...prev, title: fileNameWithoutExt }));
                }
              }
            }}
            showUploadProgress={false}
            draggable
          >
            <div style={{ padding: 32, textAlign: 'center', border: '2px dashed #dcdfe6', borderRadius: 8 }}>
              <UploadIcon style={{ fontSize: 48, color: '#ccc' }} />
              <div style={{ marginTop: 8, color: '#666' }}>点击或拖拽文件到此处上传</div>
              <div style={{ marginTop: 4, fontSize: 12, color: '#999' }}>
                支持格式: {acceptedFormats.replace(/\./g, '').toUpperCase()}
              </div>
            </div>
          </Upload>
          {file && (
            <div style={{ marginTop: 8, color: '#52c41a', fontSize: 14 }}>
              已选择: {file.name} ({(file.size / 1024 / 1024).toFixed(2)} MB)
            </div>
          )}
        </div>

        <div>
          <div style={{ marginBottom: 8, fontSize: 14, fontWeight: 500 }}>分类</div>
          <Select
            value={formData.category}
            onChange={(val) => setFormData(prev => ({ ...prev, category: val as string }))}
            options={categories.filter(c => c !== '全部').map(c => ({ label: c, value: c }))}
            placeholder="选择分类"
            clearable
          />
        </div>

        <div>
          <div style={{ marginBottom: 8, fontSize: 14, fontWeight: 500 }}>标签</div>
          <div style={{ display: 'flex', gap: 8, marginBottom: 8 }}>
            <Input
              value={tagInput}
              onChange={(val) => setTagInput(val as string)}
              placeholder="输入标签后按回车添加"
              onEnter={onAddTag}
              style={{ flex: 1 }}
            />
            <Button theme="primary" onClick={onAddTag}>添加</Button>
          </div>
          <div style={{ display: 'flex', flexWrap: 'wrap', gap: 8 }}>
            {formData.tags.map((tag, index) => (
              <Tag
                key={index}
                closable
                onClose={() => onRemoveTag(tag)}
              >
                {tag}
              </Tag>
            ))}
          </div>
        </div>

        <div>
          <div style={{ marginBottom: 8, fontSize: 14, fontWeight: 500 }}>状态</div>
          <Radio.Group
            value={formData.status}
            onChange={(val) => setFormData(prev => ({ ...prev, status: val as 'draft' | 'published' }))}
            options={[
              { label: '草稿', value: 'draft' },
              { label: '发布', value: 'published' }
            ]}
          />
        </div>

        {uploading && uploadProgress !== undefined && (
          <div>
            <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: 4 }}>
              <span style={{ fontSize: 14, color: '#666' }}>上传进度</span>
              <span style={{ fontSize: 14, color: '#333' }}>{uploadProgress}%</span>
            </div>
            <Progress percentage={uploadProgress} status={uploadProgress === 100 ? 'success' : 'active'} />
          </div>
        )}
      </div>
    </Dialog>
  );
};
