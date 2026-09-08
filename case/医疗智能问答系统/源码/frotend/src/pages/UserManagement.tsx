import { useContext, useState, useEffect } from 'react';
import { motion } from 'framer-motion';
import { AuthContext, UserRole } from '../contexts/authContext';
import Navbar from '../components/Navbar';
import Sidebar from '../components/Sidebar';
import { Card, Table, Button, Input, Select, Dialog, Form, MessagePlugin } from 'tdesign-react';
import { SearchIcon, AddIcon, EditIcon, DeleteIcon } from 'tdesign-icons-react';
import { userAPI } from '../services/api';

export default function UserManagement() {
  const { user } = useContext(AuthContext);
  const [users, setUsers] = useState<any[]>([]);
  const [filteredUsers, setFilteredUsers] = useState<any[]>([]);
  const [searchTerm, setSearchTerm] = useState('');
  const [selectedRole, setSelectedRole] = useState<UserRole | 'all'>('all');
  const [isLoading, setIsLoading] = useState(true);
  const [showAddUserModal, setShowAddUserModal] = useState(false);
  const [showEditUserModal, setShowEditUserModal] = useState(false);
  const [currentUser, setCurrentUser] = useState<any>(null);
  
  // 表单状态
  const [formData, setFormData] = useState({
    name: '',
    email: '',
    password: '',
    role: 'doctor' as UserRole
  });

  // 加载用户数据
  useEffect(() => {
    loadUsers();
  }, []);

  // 加载用户数据
  const loadUsers = async () => {
    try {
      setIsLoading(true);
      const response = await userAPI.getUsers();
      setUsers(response.data?.users || []);
    } catch (error) {
      console.error('加载用户失败:', error);
      toast.error('加载用户数据失败');
      setUsers([]); // 确保在错误情况下 users 是一个空数组
    } finally {
      setIsLoading(false);
    }
  };

  // 应用筛选
  useEffect(() => {
    applyFilters();
  }, [users, searchTerm, selectedRole]);

  const applyFilters = () => {
    // 确保 users 是一个数组
    if (!Array.isArray(users)) {
      setFilteredUsers([]);
      return;
    }
    
    let result = [...users];
    
    // 搜索筛选
    if (searchTerm) {
      const term = searchTerm.toLowerCase();
      result = result.filter(user => 
        user.name.toLowerCase().includes(term) ||
        user.email.toLowerCase().includes(term)
      );
    }
    
    // 角色筛选
    if (selectedRole !== 'all') {
      result = result.filter(user => user.role === selectedRole);
    }
    
    setFilteredUsers(result);
  };

  const handleAddUser = () => {
    setFormData({
      name: '',
      email: '',
      password: '',
      role: 'doctor'
    });
    setShowAddUserModal(true);
  };

  const handleEditUser = (user: any) => {
    setCurrentUser(user);
    setFormData({
      name: user.name,
      email: user.email,
      password: '', // 不显示密码
      role: user.role
    });
    setShowEditUserModal(true);
  };

  const handleDeleteUser = async (userId: string) => {
    // 不能删除当前登录用户
    if (userId === user?.id) {
      toast.error('不能删除当前登录的用户');
      return;
    }
    
    if (window.confirm('确定要删除此用户吗？此操作无法撤销。')) {
      try {
        await userAPI.deleteUser(userId);
        setUsers(prev => prev.filter(user => user.id !== userId));
        toast.success('用户已删除');
      } catch (error) {
        console.error('删除用户失败:', error);
        toast.error('删除用户失败');
      }
    }
  };

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    
    // 验证表单
    if (!formData.name || !formData.email) {
      toast.error('请填写所有必填字段');
      return;
    }
    
    // 验证邮箱格式
    const emailRegex = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;
    if (!emailRegex.test(formData.email)) {
      toast.error('请输入有效的邮箱地址');
      return;
    }
    
    try {
      // 添加新用户
      if (showAddUserModal) {
        if (!formData.password) {
          toast.error('请设置密码');
          return;
        }
        
        await userAPI.createUser({
          name: formData.name,
          email: formData.email,
          password: formData.password,
          role: formData.role
        });
        
        await loadUsers(); // 重新加载用户列表
        toast.success('用户已添加');
        setShowAddUserModal(false);
      }
      
      // 编辑用户
      if (showEditUserModal && currentUser) {
        const updateData: any = {
          name: formData.name,
          email: formData.email,
          role: formData.role
        };
        
        // 如果有新密码，添加到更新数据中
        if (formData.password) {
          updateData.password = formData.password;
        }
        
        await userAPI.updateUser(currentUser.id, updateData);
        
        await loadUsers(); // 重新加载用户列表
        toast.success('用户信息已更新');
        setShowEditUserModal(false);
        setCurrentUser(null);
      }
    } catch (error: any) {
      console.error('操作用户失败:', error);
      const errorMessage = error.response?.data?.message || '操作失败，请重试';
      toast.error(errorMessage);
    }
  };

  const handleCancel = () => {
    setShowAddUserModal(false);
    setShowEditUserModal(false);
    setCurrentUser(null);
  };

  const handleBulkImport = () => {
    toast.info('批量导入功能即将上线');
  };

  const handleExportExcel = async () => {
    try {
      const filters = {
        search: searchTerm || undefined,
        role: selectedRole !== 'all' ? selectedRole : undefined,
      };
      
      await userAPI.exportUsers(filters);
      toast.success('用户列表已导出');
    } catch (error: any) {
      console.error('导出用户列表失败:', error);
      const errorMessage = error.message || '导出失败，请重试';
      toast.error(errorMessage);
    }
  };

  return (
    <div className="bg-gray-50 min-h-screen flex flex-col">
      <Navbar />
      <div className="flex flex-1">
        <Sidebar />
        <main className="flex-1 ml-64 p-6">
          <div className="max-w-6xl mx-auto">
            <motion.header 
              initial={{ opacity: 0, y: -20 }}
              animate={{ opacity: 1, y: 0 }}
              transition={{ duration: 0.5 }}
              className="mb-8"
            >
              <div className="flex justify-between items-center">
                <div>
                  <h1 className="text-2xl font-bold text-gray-900">用户管理</h1>
                  <p className="text-gray-600 mt-1">管理系统用户和权限</p>
                </div>
                <div className="flex space-x-3">
                  <motion.button
                    whileHover={{ scale: 1.05 }}
                    whileTap={{ scale: 0.95 }}
                    onClick={handleBulkImport}
                    className="px-4 py-2 bg-white border border-gray-300 rounded-lg font-medium text-gray-700 hover:bg-gray-50 transition-colors flex items-center"
                  >
                    <i className="fas fa-file-import mr-2"></i>
                    批量导入
                  </motion.button>
                  <motion.button
                    whileHover={{ scale: 1.05 }}
                    whileTap={{ scale: 0.95 }}
                    onClick={handleExportExcel}
                    className="px-4 py-2 bg-green-600 text-white rounded-lg font-medium hover:bg-green-700 transition-colors flex items-center"
                  >
                    <i className="fas fa-file-excel mr-2"></i>
                    导出Excel
                  </motion.button>
                  <motion.button
                    whileHover={{ scale: 1.05 }}
                    whileTap={{ scale: 0.95 }}
                    onClick={handleAddUser}
                    className="px-4 py-2 bg-blue-600 text-white rounded-lg font-medium hover:bg-blue-700 transition-colors flex items-center"
                  >
                    <i className="fas fa-plus mr-2"></i>
                    添加用户
                  </motion.button>
                </div>
              </div>
            </motion.header>
            
            {/* 筛选和搜索 */}
            <motion.div
              initial={{ opacity: 0, y: 20 }}
              animate={{ opacity: 1, y: 0 }}
              transition={{ duration: 0.5, delay: 0.1 }}
              className="bg-white rounded-xl shadow-sm p-6 border border-gray-200 mb-6"
            >
              <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                <div>
                  <label className="block text-sm font-medium text-gray-700 mb-1">
                    搜索
                  </label>
                  <div className="relative">
                    <span className="absolute inset-y-0 left-0 flex items-center pl-3 text-gray-500">
                      <i className="fas fa-search"></i>
                    </span>
                    <input
                      type="text"
                      value={searchTerm}
                      onChange={(e) => setSearchTerm(e.target.value)}
                      className="block w-full pl-10 pr-3 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-blue-500 focus:border-blue-500 transition-all"
                      placeholder="搜索用户名或邮箱"
                    />
                    {searchTerm && (
                      <button
                        className="absolute inset-y-0 right-0 flex items-center pr-3 text-gray-500"
                        onClick={() => setSearchTerm('')}
                      >
                        <i className="fas fa-times-circle"></i>
                      </button>
                    )}
                  </div>
                </div>
                
                <div>
                  <label className="block text-sm font-medium text-gray-700 mb-1">
                    用户角色
                  </label>
                  <select
                    value={selectedRole}
                    onChange={(e) => setSelectedRole(e.target.value as UserRole | 'all')}
                    className="block w-full px-3 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-blue-500 focus:border-blue-500 transition-all appearance-none bg-white"
                  >
                    <option value="all">所有角色</option>
                    <option value="doctor">医生</option>
                    <option value="admin">管理员</option>
                  </select>
                </div>
              </div>
            </motion.div>
            
            {/* 用户列表 */}
            <motion.div
              initial={{ opacity: 0, y: 20 }}
              animate={{ opacity: 1, y: 0 }}
              transition={{ duration: 0.5, delay: 0.2 }}
            >
              {isLoading ? (
                <div className="bg-white rounded-xl shadow-sm p-6 border border-gray-200 flex flex-col items-center justify-center h-64">
                  <div className="w-12 h-12 border-4 border-blue-200 border-t-blue-600 rounded-full animate-spin"></div>
                  <p className="mt-4 text-gray-600">加载用户中...</p>
                </div>
              ) : filteredUsers.length === 0 ? (
                <div className="bg-white rounded-xl shadow-sm p-6 border border-gray-200 flex flex-col items-center justify-center h-64">
                  <div className="w-16 h-16 bg-gray-100 rounded-full flex items-center justify-center mb-4">
                    <i className="fas fa-users text-gray-400 text-2xl"></i>
                  </div>
                  <p className="text-gray-600">没有找到匹配的用户</p>
                  <button
                    onClick={() => {
                      setSearchTerm('');
                      setSelectedRole('all');
                    }}
                    className="mt-4 px-4 py-2 bg-blue-50 text-blue-600 rounded-lg text-sm font-medium hover:bg-blue-100 transition-colors"
                  >
                    清除筛选条件
                  </button>
                </div>
              ) : (
                <div className="bg-white rounded-xl shadow-sm border border-gray-200 overflow-hidden">
                  <div className="overflow-x-auto">
                    <table className="min-w-full divide-y divide-gray-200">
                      <thead className="bg-gray-50">
                        <tr>
                          <th scope="col" className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">
                            用户名
                          </th>
                          <th scope="col" className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">
                            邮箱
                          </th>
                          <th scope="col" className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">
                            角色
                          </th>
                          <th scope="col" className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">
                            最后登录
                          </th>
                          <th scope="col" className="px-6 py-3 text-right text-xs font-medium text-gray-500 uppercase tracking-wider">
                            操作
                          </th>
                        </tr>
                      </thead>
                      <tbody className="bg-white divide-y divide-gray-200">
                        {filteredUsers.map((user, index) => (
                          <motion.tr 
                            key={user.id} 
                            className="hover:bg-gray-50"
                            initial={{ opacity: 0, y: 10 }}
                            animate={{ opacity: 1, y: 0 }}
                            transition={{ duration: 0.3, delay: 0.1 * index }}
                          >
                            <td className="px-6 py-4 whitespace-nowrap">
                              <div className="flex items-center">
                                <div className="w-8 h-8 bg-blue-100 rounded-full flex items-center justify-center mr-3">
                                  <span className="text-blue-600 font-medium">{user.name.charAt(0)}</span>
                                </div>
                                <div>
                                  <div className="text-sm font-medium text-gray-900">{user.name}</div>
                                </div>
                              </div>
                            </td>
                            <td className="px-6 py-4 whitespace-nowrap">
                              <div className="text-sm text-gray-900">{user.email}</div>
                            </td>
                            <td className="px-6 py-4 whitespace-nowrap">
                              <span className={`px-2 py-1 inline-flex text-xs leading-5 font-semibold rounded-full ${
                                user.role === 'admin' 
                                  ? 'bg-red-100 text-red-800' 
                                  : 'bg-blue-100 text-blue-800'
                              }`}>
                                {user.role === 'admin' ? '管理员' : '医生'}
                              </span>
                            </td>
                            <td className="px-6 py-4 whitespace-nowrap text-sm text-gray-500">
                              {user.lastLogin 
                                ? new Date(user.lastLogin).toLocaleString('zh-CN') 
                                : '从未登录'}
                            </td>
                            <td className="px-6 py-4 whitespace-nowrap text-right text-sm font-medium">
                              <button
                                onClick={() => handleEditUser(user)}
                                className="text-blue-600 hover:text-blue-900 mr-3"
                              >
                                编辑
                              </button>
                              <button
                                onClick={() => handleDeleteUser(user.id)}
                                className="text-red-600 hover:text-red-900"
                                disabled={user.id === currentUser?.id}
                              >
                                删除
                              </button>
                            </td>
                          </motion.tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                  
                  {/* 分页 */}
                  <div className="px-6 py-4 border-t border-gray-200 flex items-center justify-between">
                    <div className="hidden sm:flex-1 sm:flex sm:items-center sm:justify-between">
                      <div>
                        <p className="text-sm text-gray-700">
                          显示 <span className="font-medium">1</span> 到 <span className="font-medium">{filteredUsers.length}</span> 条，共 <span className="font-medium">{filteredUsers.length}</span> 条结果
                        </p>
                      </div>
                      <div>
                        <nav className="relative z-0 inline-flex rounded-md shadow-sm -space-x-px" aria-label="Pagination">
                          <button className="relative inline-flex items-center px-2 py-2 rounded-l-md border border-gray-300 bg-white text-sm font-medium text-gray-500 hover:bg-gray-50">
                            <span className="sr-only">上一页</span>
                            <i className="fas fa-chevron-left text-xs"></i>
                          </button>
                          <button className="relative inline-flex items-center px-4 py-2 border border-gray-300 bg-blue-50 text-sm font-medium text-blue-600">
                            1
                          </button>
                          <button className="relative inline-flex items-center px-2 py-2 rounded-r-md border border-gray-300 bg-white text-sm font-medium text-gray-500 hover:bg-gray-50">
                            <span className="sr-only">下一页</span>
                            <i className="fas fa-chevron-right text-xs"></i>
                          </button>
                        </nav>
                      </div>
                    </div>
                  </div>
                </div>
              )}
            </motion.div>
          </div>
        </main>
      </div>
      
      {/* 添加/编辑用户模态框 */}
      {(showAddUserModal || showEditUserModal) && (
        <motion.div
          initial={{ opacity: 0 }}
          animate={{ opacity: 1 }}
          exit={{ opacity: 0 }}
          className="fixed inset-0 bg-black bg-opacity-50 z-50 flex items-center justify-center p-4"
        >
          <motion.div
            initial={{ opacity: 0, y: -20 }}
            animate={{ opacity: 1, y: 0 }}
            exit={{ opacity: 0, y: -20 }}
            className="bg-white rounded-xl shadow-xl w-full max-w-md p-6"
          >
            <h3 className="text-lg font-semibold text-gray-900 mb-4">
              {showAddUserModal ? '添加新用户' : '编辑用户信息'}
            </h3>
            
            <form onSubmit={handleSubmit} className="space-y-4">
              <div>
                <label htmlFor="name" className="block text-sm font-medium text-gray-700 mb-1">
                  用户名 <span className="text-red-500">*</span>
                </label>
                <input
                  type="text"
                  id="name"
                  value={formData.name}
                  onChange={(e) => setFormData(prev => ({ ...prev, name: e.target.value }))}
                  className="block w-full px-3 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-blue-500 focus:border-blue-500 transition-all"
                  placeholder="输入用户名"
                />
              </div>
              
              <div>
                <label htmlFor="email" className="block text-sm font-medium text-gray-700 mb-1">
                  邮箱 <span className="text-red-500">*</span>
                </label>
                <input
                  type="email"
                  id="email"
                  value={formData.email}
                  onChange={(e) => setFormData(prev => ({ ...prev, email: e.target.value }))}
                  className="block w-full px-3 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-blue-500 focus:border-blue-500 transition-all"
                  placeholder="输入邮箱地址"
                />
              </div>
              
              <div><label htmlFor="password" className="block text-sm font-medium text-gray-700 mb-1">
                  密码 {showEditUserModal ? '(留空表示不修改)' : '<span className="text-red-500">*</span>'}
                </label>
                <input
                  type="password"
                  id="password"
                  value={formData.password}
                  onChange={(e) => setFormData(prev => ({ ...prev, password: e.target.value }))}
                  className="block w-full px-3 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-blue-500 focus:border-blue-500 transition-all"
                  placeholder="输入密码"
                />
              </div>
              
              <div>
                <label htmlFor="role" className="block text-sm font-medium text-gray-700 mb-1">
                  用户角色 <span className="text-red-500">*</span>
                </label>
                <select
                  id="role"
                  value={formData.role}
                  onChange={(e) => setFormData(prev => ({ ...prev, role: e.target.value as UserRole }))}
                  className="block w-full px-3 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-blue-500 focus:border-blue-500 transition-all appearance-none bg-white"
                >
                  <option value="doctor">医生</option>
                  <option value="admin">管理员</option>
                </select>
              </div>
              
              <div className="flex justify-end space-x-3 pt-4 border-t border-gray-200">
                <button
                  type="button"
                  onClick={handleCancel}
                  className="px-4 py-2 border border-gray-300 rounded-lg font-medium text-gray-700 hover:bg-gray-50 transition-colors"
                >
                  取消
                </button>
                <button
                  type="submit"
                  className="px-4 py-2 bg-blue-600 text-white rounded-lg font-medium hover:bg-blue-700 transition-colors"
                >
                  {showAddUserModal ? '添加' : '保存'}
                </button>
              </div>
            </form>
          </motion.div>
        </motion.div>
      )}
    </div>
  );
}