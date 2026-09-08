<template>
  <div class="document-edit">
    <div class="edit-header">
      <h1>{{ isEdit ? '编辑文档' : '创建文档' }}</h1>
      
      <div class="edit-actions">
        <el-button @click="router.back()">取消</el-button>
        <el-button type="primary" @click="handleSave" :loading="saving">
          保存
        </el-button>
      </div>
    </div>
    
    <el-form ref="formRef" :model="form" :rules="rules" class="edit-form">
      <el-form-item prop="title">
        <el-input
          v-model="form.title"
          placeholder="请输入文档标题"
          size="large"
        />
      </el-form-item>
      
      <el-form-item prop="category_id">
        <el-select v-model="form.category_id" placeholder="选择分类" clearable>
          <el-option
            v-for="category in categories"
            :key="category.id"
            :label="category.name"
            :value="category.id"
          />
        </el-select>
      </el-form-item>
      
      <el-form-item prop="content">
        <el-input
          v-model="form.content"
          type="textarea"
          :rows="20"
          placeholder="请输入文档内容（支持Markdown格式）"
        />
      </el-form-item>
      
      <el-form-item>
        <el-checkbox v-model="form.is_pinned">置顶</el-checkbox>
        <el-checkbox v-model="form.is_featured">精选</el-checkbox>
      </el-form-item>
    </el-form>
  </div>
</template>

<script setup lang="ts">
import { ref, reactive, onMounted, computed } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { useDocumentsStore } from '@/stores/documents'
import { documentsApi } from '@/api/documents'
import { ElMessage } from 'element-plus'
import type { FormInstance, FormRules } from 'element-plus'

const route = useRoute()
const router = useRouter()
const documentsStore = useDocumentsStore()

const formRef = ref<FormInstance>()
const saving = ref(false)
const categories = ref<any[]>([])

const isEdit = computed(() => !!route.params.id)

const form = reactive({
  title: '',
  content: '',
  category_id: undefined as number | undefined,
  is_pinned: false,
  is_featured: false
})

const rules: FormRules = {
  title: [
    { required: true, message: '请输入文档标题', trigger: 'blur' }
  ]
}

const fetchCategories = async () => {
  try {
    const response = await documentsApi.getCategories()
    categories.value = response.categories
  } catch (error) {
    console.error('Failed to fetch categories:', error)
  }
}

const fetchDocument = async () => {
  if (!route.params.id) return
  
  try {
    const document = await documentsStore.fetchDocument(Number(route.params.id))
    form.title = document.title
    form.content = document.content || ''
    form.category_id = document.category?.id
    form.is_pinned = document.is_pinned
    form.is_featured = document.is_featured
  } catch (error) {
    console.error('Failed to fetch document:', error)
    ElMessage.error('获取文档失败')
  }
}

const handleSave = async () => {
  if (!formRef.value) return
  
  await formRef.value.validate(async (valid) => {
    if (valid) {
      saving.value = true
      try {
        if (isEdit.value) {
          await documentsStore.updateDocument(Number(route.params.id), form)
          ElMessage.success('更新成功')
        } else {
          await documentsStore.createDocument(form)
          ElMessage.success('创建成功')
        }
        router.push('/documents')
      } catch (error) {
        console.error('Failed to save document:', error)
        ElMessage.error('保存失败')
      } finally {
        saving.value = false
      }
    }
  })
}

onMounted(() => {
  fetchCategories()
  if (isEdit.value) {
    fetchDocument()
  }
})
</script>

<style lang="scss" scoped>
@use '@/styles/variables.scss' as *;

.document-edit {
  max-width: 900px;
  margin: 0 auto;
  padding: 20px;
}

.edit-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 30px;
  
  h1 {
    margin: 0;
    font-size: 24px;
    color: $text-primary;
  }
}

.edit-form {
  background: $bg-card;
  backdrop-filter: blur(12px);
  padding: 30px;
  border-radius: $radius-lg;
  border: 1px solid $border-color;
  box-shadow: $shadow-md;
}
</style>